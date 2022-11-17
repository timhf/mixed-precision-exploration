"""
Run a quantization exploration from a workload .yaml file
Usage:
    $ python path/to/main.py --workloads resnet50.yaml
Usage:
    $ python path/to/main.py --workloads fcn-resnet50.yaml      # TorchVision: fully connected ResNet50
                                         resnet50.yaml          # TorchVision: ResNet50
                                         yolov5.yaml            # TorchVision: YoloV5
                                         lenet5.yaml            # Custom: LeNet5
"""
import os
import argparse
import numpy as np
from datetime import datetime
import pickle
import importlib

# import troch quantization and activate the replacement of modules
from pytorch_quantization import quant_modules
quant_modules.initialize()

from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.operators.repair.rounding import RoundingRepair
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PolynomialMutation
from pymoo.optimize import minimize
from pymoo.termination import get_termination
from pymoo.core.evaluator import Evaluator

import src.exploration.weighting_functions
from src.utils.logger import logger
from src.utils.setup import build_dataloader_generators, setup_torch_device, setup_model
from src.utils.workload import Workload
from src.utils.data_loader_generator import DataLoaderGenerator

from src.exploration.problems import LayerwiseQuantizationProblem
from src.quantization.quantized_model import QuantizedModel


RESULTS_DIR = "./results"


def save_result(res, model_name, dataset_name):
    """Save the result object from the exploration as a pickle file.

    Args:
        res (obj):
            The result object to save.
        model_name (str):
            The name of the model this result object belongs to.
            This is used as a prefix for the saved file.
    """
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    filename = 'exploration_{}_{}_{}.pkl'.format(
        model_name, dataset_name, date_str)

    with open(os.path.join(RESULTS_DIR, filename), "wb") as res_file:
        pickle.dump(res, res_file)

    logger.info(f"Saved result object to: {filename}")



def explore_quantization(workload: Workload, calibration_file: str, 
                         skip_baseline: bool, progress: bool, 
                         verbose: bool) -> None:
    """Runs the given workload.

    Args:
        workload (Workload):
            The workload loaded from a workload yaml file.
        collect_baseline (bool):
            Whether to collect basline metrics of the model without quantization.
    """
    dataloaders = build_dataloader_generators(workload['exploration']['datasets'])
    model, accuracy_function = setup_model(workload['model'])
    device = setup_torch_device()
    weighting_function = getattr(importlib.import_module('src.exploration.weighting_functions'), 
                                 workload['exploration']['bit_weighting_function'], None)
    assert weighting_function is not None and callable(weighting_function), "error loading weighting function"

    # now switch to quantized model
    qmodel = QuantizedModel(model, device, 
                            weighting_function=weighting_function,
                            verbose=verbose)
    logger.info("Added {} Quantizer modules to the model".format(len(qmodel.quantizer_modules)))

    if not skip_baseline:
        # collect model basline information
        baseline_dataloader = dataloaders['baseline']
        logger.info("Collecting baseline...")
        qmodel.disable_quantization()
        baseline = accuracy_function(qmodel.model, baseline_dataloader, title="Baseline Generation")
        qmodel.enable_quantization()
        logger.info(f"Done. Baseline accuracy: {baseline:.3f}")

    # Load the previously generated calibration file
    logger.info(f"Loading calibration file: {calibration_file}")
    qmodel.load_parameters(calibration_file)

    # configure exploration
    # FIXME: add to workload file
    problem = LayerwiseQuantizationProblem(
        qmodel,
        dataloaders['exploration'],
        accuracy_function,
        num_bits_upper_limit=workload['exploration']['bit_widths'][1],
        num_bits_lower_limit=workload['exploration']['bit_widths'][0],
        min_accuracy=workload['exploration']['minimum_accuracy'],
        progress=progress
    )

    # TODO put into own module and pass args from workload
    # TODO set through workload
    sampling = IntegerRandomSampling()
    crossover = SBX(prob_var=workload['exploration']['nsga']['crossover_prob'],
                    eta=workload['exploration']['nsga']['crossover_eta'],
                    repair=RoundingRepair(), 
                    vtype=float)
    mutation = PolynomialMutation(prob=workload['exploration']['nsga']['mutation_prob'],
                                  eta=workload['exploration']['nsga']['mutation_eta'],
                                  repair=RoundingRepair())

    algorithm = NSGA2(
        pop_size=workload['exploration']['nsga']['pop_size'],
        n_offsprings=workload['exploration']['nsga']['offsprings'],
        sampling=sampling,
        crossover=crossover,
        mutation=mutation,
        eliminate_duplicates=True,
    )

    termination = get_termination("n_gen", workload['exploration']['nsga']['generations'])

    logger.info("Starting problem minimization.")

    res = minimize(
        problem,
        algorithm,
        termination,
        seed=1,
        save_history=True,
        verbose=True
    )

    logger.info("Finished problem minimization.")

    if res.F is None:
        logger.warning("No solutions found for the given constraints.")
        return

    # since we inverted our objective functions we have to invert the result back
    res.F = np.abs(res.F)

    return res



if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("calibration_file")
    parser.add_argument(
        "workload", 
        help="The path to the workload yaml file.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose information.")
    parser.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="Show the current inference progress.")
    parser.add_argument(
        "-fn",
        "--filename",
        help="override default filename for calibration pickle file")
    parser.add_argument(
        "-s",
        "--skip-baseline",
        help="skip baseline computation to save time",
        action="store_true"
    )
    opt = parser.parse_args()

    logger.info("Quantization Exploration Started")

    workload_file = opt.workload
    if os.path.isfile(workload_file):
        workload = Workload(workload_file)
        results = explore_quantization(workload, opt.calibration_file, opt.skip_baseline, opt.progress, opt.verbose)
        save_result(results, workload['model']['type'], workload['dataset']['type'])

    else:
        logger.warning("Declared workload file could not be found.")
        raise Exception(f"No file {opt.workload} found.")

    logger.info("Quantization Exploration Finished")

