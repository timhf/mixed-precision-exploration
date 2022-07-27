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
import sys
import shutil
import argparse
import numpy as np
from src.utils.logger import logger

from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.factory import get_termination, get_crossover, get_mutation, get_sampling
from pymoo.optimize import minimize

from src.utils.setup import setup
from src.utils.workload import Workload
from src.utils.predicates import conv2d_predicate
from src.utils.data_loader_generator import DataLoaderGenerator

from src.exploration.problems import LayerwiseQuantizationProblem
from src.quantization.quantization import QuantizedActivationsModel

LOG_DIR = "../logs"
RESULTS_DIR = "../results"
WORKLOADS_DIR = "../workloads"


def baseline_collection(
    model, accuracy_function: callable, baseline_data_loader
) -> None:
    """Collect the baseline metrics for a given model-

    Args:
        model (Model): The model to collect the baseline on.
        accuracy_function (callable): The accuracy function to evaluate the model.
        baseline_data_loader (object): The data loader that provides the evaluation samples.
    """
    logger.info("Collecting basline...")
    baseline = accuracy_function(model, baseline_data_loader)
    logger.info(f"Done. Baseline accuracy: {baseline}")


def run(workload: Workload, collect_baseline: bool) -> None:
    """Runs the given workload.

    Args:
        workload (Workload):
            The workload loaded from a workload yaml file.
        collect_baseline (bool):
            Whether to collect basline metrics of the model without quantization.
    """
    model, accuracy_function, dataset, collate_fn = setup(workload)
    data_loader_generator = DataLoaderGenerator(dataset, collate_fn)

    if collect_baseline:
        # collect model basline information
        baseline_data_loader = data_loader_generator.get_data_loader()
        baseline_collection(model, accuracy_function, baseline_data_loader)

    quant_model = QuantizedActivationsModel(model, conv2d_predicate)

    # calibration of quantization parameters
    # TODO maybe move into QuantizedActivationsModel
    n_calibration_samples = 1024
    calibration_batch_size = 32  # 512
    calibration_data_loader = data_loader_generator.get_data_loader(
        n_calibration_samples, calibration_batch_size
    )
    quant_model.calibrate(calibration_data_loader)

    # configure exploration

    problem = LayerwiseQuantizationProblem(
        quant_model,
        data_loader_generator,
        accuracy_function,
        sample_limit=128,
    )

    # TODO put into own module and pass args from workload
    # TODO set through workload
    algorithm = NSGA2(
        pop_size=5,
        n_offsprings=2,
        sampling=get_sampling("int_random"),
        crossover=get_crossover("int_sbx", prob=1.0, eta=3.0),
        mutation=get_mutation("int_pm", eta=3.0),
        eliminate_duplicates=True,
    )

    termination = get_termination("n_gen", 10)

    logger.info("Starting problem minimization.")

    res = minimize(
        problem,
        algorithm,
        termination,
        seed=1,
        save_history=True,
        verbose=True,
    )

    logger.info("Finished problem minimization.")

    if res.F is None:
        logger.warning("No solutions found for the given constraints.")
        return

    # since we inverted our objective functions we have to invert the result back
    res.F = np.abs(res.F)

    print(res)


def clean() -> None:
    """
    Cleans the output directories by deleting their contents.
    """

    logger.info("Cleaning up previous results.")

    shutil.rmtree(LOG_DIR)
    shutil.rmtree(RESULTS_DIR)

    logger.info("Finished")


def parse_opt() -> dict:
    """Parses the arguments provided on the cli.

    Returns:
        dict: The parsed argument options.
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("-w", "--workload", help="The path to the workload yaml file.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose information.",
    )
    parser.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="Show the current inference progress.",
    )
    parser.add_argument(
        "-cb",
        "--collect_baseline",
        action="store_true",
        help="Collect baseline stats of the model.",
    )
    parser.add_argument(
        "-c", "--clean", action="store_true", help="Clean up previous results."
    )
    opt = parser.parse_args()

    return opt


def main(opt: dict) -> None:
    """Handles the cli arguments.

    Args:
        opt (dict): The options provided through the cli.

    Raises:
        Exception: If not cleaning and no workload file is given.
        Exception: If the provided workload file could not be found.
    """

    logger.info("Started")

    if opt.clean:
        clean()
        sys.exit(0)

    workload_file = opt.workload

    if workload_file is None:
        logger.warning("No workload file declared.")
        raise Exception("Please specifiy a workload file.")

    if os.path.isfile(workload_file):

        workload = Workload(workload_file)
        run(workload, opt.collect_baseline)

    else:
        logger.warning("Declared workload file could not be found.")
        raise Exception(f"No file {opt.workload} found.")

    logger.info("Finished")


if __name__ == "__main__":
    options = parse_opt()
    main(options)