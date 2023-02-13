import os
import argparse
import pandas as pd

from model_explorer.utils.logger import logger
from model_explorer.exploration.retrain_model import retrain_model
from model_explorer.utils.workload import Workload
from model_explorer.result_handling.collect_results import collect_results
from model_explorer.result_handling.save_results import save_results_df_to_csv



def select_individuals(results_path: str, count: int) -> pd.DataFrame:
    results_collection = collect_results(results_path)

    results_collection.drop_duplicate_parameters()
    logger.debug("Loaded in total {} individuals".format(
        len(results_collection.individuals)))

    # select individuals based on a prodcut of normed F_0 and accuracy
    ind_df = results_collection.to_dataframe()
    ind_df['F_0'] = -ind_df['F_0']
    ind_df['norm_f0'] = ind_df['F_0'] / ind_df['F_0'].max()
    ind_df['norm_acc'] = ind_df['accuracy'] / ind_df['accuracy'].max()
    ind_df['weighted'] = ind_df['norm_f0'] * ind_df['norm_acc']

    ind_filtered = ind_df.sort_values(by=['weighted'], ascending=False)
    ind_filtered = ind_filtered.head(count)

    return ind_filtered


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("workload_file")
    parser.add_argument("results_path")
    parser.add_argument("output_dir",
                        help="Folder where to place the retrained model parameters")
    parser.add_argument('-n',
                        "--top_elements",
                        help="Select n individuals with the lowest bits",
                        type=int)
    parser.add_argument("-v",
                        "--verbose",
                        action="store_true",
                        help="Show verbose information.")
    parser.add_argument("-p",
                        "--progress",
                        action="store_true",
                        help="Show the current inference progress.")
    opt = parser.parse_args()

    logger.info("Retraining of {} individuals started".format(
        opt.top_elements))

    workload_file = opt.workload_file

    output_dir = opt.output_dir
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if os.path.isfile(workload_file):
        workload = Workload(workload_file)
        individuals = select_individuals(opt.results_path, opt.top_elements)
        results = retrain_model(workload, individuals, output_dir,
                                opt.progress, opt.verbose)
        save_results_df_to_csv('retrain', results, workload['problem']['problem_function'],
                               workload['model']['type'], workload['reevaluation']['datasets']['reevaluate']['type'])

    else:
        logger.warning("Declared workload file could not be found.")
        raise Exception(f"No file {opt.workload} found.")

    logger.info("Retraining Process Finished")