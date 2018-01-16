# License: BSD 3 clause
import itertools
import os
import pickle
import pprint
import time
from collections import OrderedDict
from itertools import chain

import matplotlib.pyplot as plt
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression as LogisticRegressionSKlearn
from sklearn.metrics import roc_curve, auc

from tick.dataset import fetch_tick_dataset
from tick.dataset.url_dataset import fetch_url_dataset
from tick.inference import LogisticRegression as LogisticRegressionTick

TOL = 1e-16

C_FORMULAS = {
    'n': lambda n: n,
    'sqrt(n)': lambda n: np.sqrt(n),
}


def create_dir_if_missing(file_path):
    directory = os.path.dirname(file_path)
    try:
        os.stat(directory)
    except:
        os.mkdir(directory)


def write_to_file(file_path, text):
    create_dir_if_missing(file_path)

    with open(file_path, 'a') as f:
        f.write(text)


def load_dataset(dataset, *args):
    if dataset == 'url':
        n_url_days = args[0]
        dataset_file_name = 'url_d{}'.format(n_url_days)
        X, y = fetch_url_dataset(n_url_days)

    elif dataset == 'breast':
        dataset_file_name = 'breast'
        X, y = sklearn.datasets.load_breast_cancer(return_X_y=True)

    elif dataset == 'adult':
        dataset_file_name = 'adult'
        X, y = fetch_tick_dataset('binary/adult/adult.trn.bz2')

    else:
        raise ValueError('Unknown dataset {}'.format(dataset))

    print('SHAPES', X.shape, y.shape)
    return dataset_file_name, X, y


def load_train_test(X, y, p_test=0.2):
    test_size = int(p_test * len(y))

    np.random.seed(29389328)
    n_samples = len(y)
    shuffled_index = np.random.permutation(np.arange(n_samples))
    test_index = shuffled_index[:test_size]
    train_index = shuffled_index[test_size:]

    X_train, y_train = X[train_index, :], y[train_index]
    X_test, y_test = X[test_index, :], y[test_index]

    return X_train, y_train, X_test, y_test


def create_learner(lib, solver, C, max_iter, penalty, train_size):
    if lib == 'scikit':
        scaled_C = C / train_size
        learner = LogisticRegressionSKlearn(
            C=scaled_C, penalty=penalty, solver=solver, max_iter=max_iter,
            fit_intercept=False,
            tol=TOL, random_state=10392)
    else:
        learner = LogisticRegressionTick(
            C=C, penalty=penalty, solver=solver, max_iter=max_iter,
            fit_intercept=False,
            tol=TOL, random_state=10392,
            record_every=10000, print_every=10000, verbose=True)

    return learner


def run_solver(X_train, y_train, lib, solver, C, max_iter, penalty):
    train_size = len(y_train)
    learner = create_learner(lib, solver, C, max_iter, penalty, train_size)

    start_time = time.time()
    learner.fit(X_train, y_train)
    elapsed_time = time.time() - start_time

    return learner, elapsed_time


def learner_coeffs(learner):
    if isinstance(learner, LogisticRegressionSKlearn):
        if learner.fit_intercept:
            return np.hstack((learner.coef_[0], learner.intercept_))
        else:
            return learner.coef_[0]
    else:
        return learner._solver_obj.solution


def evaluate_objective(learner, X_train, y_train, tick_learner):
    coeffs = learner_coeffs(learner)

    tick_learner._model_obj.fit(X_train, y_train)
    train_objective = tick_learner._model_obj.loss(coeffs)
    train_objective += tick_learner._prox_obj.value(coeffs)

    return train_objective


def evaluate_auc(learner, X_test, y_test):
    fpr, tpr, _ = roc_curve(y_test, learner.predict_proba(X_test)[:, 1])
    auc_value = auc(fpr, tpr)

    return auc_value


def run_and_evaluate(dataset_file_name, X_train, y_train, X_test, y_test,
                     lib, solver, C_formula, max_iter, penalty):
    n_train_samples = len(y_train)
    C = C_FORMULAS[C_formula](n_train_samples)
    learner, elapsed_time = run_solver(
        X_train, y_train, lib, solver, C, max_iter, penalty)

    tick_learner = LogisticRegressionTick(C=C, penalty=penalty,
                                          fit_intercept=False)

    train_objective = evaluate_objective(learner, X_train, y_train,
                                         tick_learner)
    auc_value = evaluate_auc(learner, X_test, y_test)

    learner_name = '{}_{}_{}_{}_{}.pkl'.format(
        lib, solver, penalty, C_formula, max_iter)
    learner_save_file = 'learners/{}/{}'.format(dataset_file_name, learner_name)

    create_dir_if_missing(learner_save_file)
    with open(learner_save_file, 'wb') as f:
        pickle.dump(learner, f)
        print('saved in ', learner_save_file)

    return elapsed_time, train_objective, auc_value


def add_nest(d, value, *keys):
    nest_d = d
    for key in keys[:-1]:
        if key not in nest_d:
            nest_d[key] = {}
        nest_d = nest_d[key]
    nest_d[keys[-1]] = value


if __name__ == '__main__':

    do_training = False

    datasets = ['adult']

    scikit_solvers = ['saga', 'liblinear']
    tick_solvers = ['saga']

    C_formulas = ['n', 'sqrt(n)']
    penalties = ['l1', 'l2']

    max_iters = [10, 20, 30, 50, 70, 100]

    scikit_runs = itertools.product(
        scikit_solvers, C_formulas, penalties, max_iters)

    tick_runs = itertools.product(
        tick_solvers, C_formulas, penalties, max_iters)

    agg_results = OrderedDict()
    for dataset in datasets:
        dataset_file_name, X, y = load_dataset(dataset)
        X_train, y_train, X_test, y_test = load_train_test(X, y)
        n_train_samples = len(y_train)

        args = []
        results = []
        for solver, C_formula, penalty, max_iter in scikit_runs:
            arg = [
                dataset_file_name, X_train, y_train, X_test, y_test,
                'scikit', solver, C_formula, max_iter, penalty
            ]

            args += [arg]

        for solver, C_formula, penalty, max_iter in tick_runs:
            arg = [
                dataset_file_name, X_train, y_train, X_test, y_test,
                'tick', solver, C_formula, max_iter, penalty
            ]

            args += [arg]

        if do_training:
            for arg in args:
                results += [run_and_evaluate(*arg)]

            for arg, result in zip(args, results):
                dataset_file_name, X_train, y_train, X_test, y_test, \
                lib, solver, C_formula, max_iter, penalty = arg

                elapsed_time, train_objective, auc_value = result

                path = [
                    dataset_file_name, penalty, C_formula, lib, solver, max_iter]

                add_nest(agg_results, elapsed_time, *(path + ['elapsed_time']))
                add_nest(agg_results, train_objective, *(path + ['objective']))
                add_nest(agg_results, auc_value, *(path + ['auc']))

            result_file_name_base = 'results/{}-{}'.format(
                dataset_file_name, time.strftime('%H:%M:%S'))
            write_to_file('{}.txt'.format(result_file_name_base),
                          pprint.pformat(agg_results[dataset_file_name]))
            with open('{}.pkl'.format(result_file_name_base), 'wb') as f:
                pickle.dump(agg_results[dataset_file_name], f)

        else:
            dataset_files = [file_name
                             for file_name in os.listdir('results')
                             if file_name.startswith('adult-')
                             and file_name.endswith('pkl')]
            dataset_files.sort()
            last_result_file = dataset_files[-1]

            dict_path = 'results/{}'.format(last_result_file)

            with open(dict_path, 'rb') as f:
                agg_results[dataset_file_name] = pickle.load(f)

    for dataset_file_name in agg_results.keys():
        penalties = list(agg_results[dataset_file_name].keys())
        C_formulas = list(
            agg_results[dataset_file_name][penalties[0]].keys())
        libs = list(
            agg_results[dataset_file_name][penalties[0]][C_formulas[0]].keys())

        n_rows = len(penalties)
        n_cols = len(C_formulas)

        fig, axes = plt.subplots(n_rows, n_rows)
        if n_rows == 1:
            axes = [axes]
        if n_cols == 1:
            axes = [axes]

        min_objectives = {}
        for penalty, C_formula in itertools.product(penalties, C_formulas):
            min_objective = 1e300
            for lib in agg_results[dataset_file_name][penalty][C_formula].keys():
                lib_solvers = \
                agg_results[dataset_file_name][penalty][C_formula][lib]
                for solver in lib_solvers.keys():
                    min_objective = min(min_objective, min([
                        lib_solvers[solver][max_iter]['objective']
                        for max_iter in lib_solvers[solver]
                    ]))

            add_nest(min_objectives, min_objective, penalty, C_formula)

        for penalty, C_formula, lib in itertools.product(
                penalties, C_formulas, libs):
            row = penalties.index(penalty)
            col = C_formulas.index(C_formula)

            ax = axes[row][col]

            lib_solvers = agg_results[dataset_file_name][penalty][C_formula][lib]
            for solver in lib_solvers.keys():
                label = '{} {}'.format(lib, solver)

                times = []
                objectives = []
                max_iters = list(lib_solvers[solver].keys())
                max_iters.sort()
                for max_iter in max_iters:
                    print(max_iter)
                    times += [lib_solvers[solver][max_iter]['elapsed_time']]
                    objectives += [lib_solvers[solver][max_iter]['objective']]

                objectives = np.array(objectives)
                diff_objectives = objectives - min_objectives[penalty][C_formula]
                diff_objectives += min(diff_objectives[diff_objectives != 0]) / 2

                ax.plot(times, diff_objectives, label=label)
                ax.set_yscale('log')

                print(times)

            ax.legend()

        plt.show()



def plot_best_params(C):
    dataset_file_name, X, y = load_dataset()
    print(X.shape)

    test_size = int(0.2 * len(y))
    train_size = len(y) - test_size

    tick_learner = LogisticRegressionTick(C=C, penalty='l1',
                                          fit_intercept=False)

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))

    times = {}
    auc_values = {}
    objectives = {}

    libs = ['tick', 'scikit']
    for lib in libs:
        times[lib] = []
        auc_values[lib] = []
        objectives[lib] = []

        for max_iter in [10 * i for i in range(1, 11)]:# + [200, 300]:

            if lib == 'scikit':
                learner = LogisticRegressionSKlearn(solver='saga',
                                                    max_iter=max_iter,
                                                    tol=tol,
                                                    C=C / train_size,
                                                    penalty='l1',
                                                    fit_intercept=False)
            else:
                learner = LogisticRegressionTick(solver='saga',
                                                 max_iter=max_iter,
                                                 tol=tol,
                                                 record_every=10000,
                                                 print_every=10000,
                                                 verbose=True,
                                                 C=C, penalty='l1',
                                                 random_state=10392,
                                                 fit_intercept=False)

            _, elapsed_time, auc_value, train_objective = run_best_C(
                learner, X, y, tick_learner, test_size)

            times[lib] += [elapsed_time]
            auc_values[lib] += [auc_value]
            objectives[lib] += [train_objective]

        print(objectives)

    min_objectives = min(chain.from_iterable([objectives[lib] for lib in libs]))
    for lib in libs:
        axes[0].plot(times[lib], auc_values[lib], marker='x', label=lib)

        lib_objectives = np.array(objectives[lib]) - min_objectives
        lib_objectives += min(lib_objectives[lib_objectives != 0]) / 2
        axes[1].plot(times[lib], lib_objectives,
                     marker='x', label=lib)

    axes[1].set_yscale('log')

    axes[0].set_xlabel('time')
    axes[0].set_title('AUC')
    axes[1].set_xlabel('time')
    axes[1].set_title('distance to optimal objective')
    axes[0].legend()
    axes[1].legend()

    fig.tight_layout()
    plt.show()