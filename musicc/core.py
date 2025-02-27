
"""
MUSiCC
"""

# to comply with both Py2 and Py3
from __future__ import absolute_import, division, print_function

# general imports
import os
import sys
import warnings
from time import time
import base64
import uuid

# specific imports that need to be pre-installed
import numpy as np
from scipy import stats
import pandas as pd
from sklearn.model_selection import KFold
from sklearn import linear_model  # for the LASSO
from sklearn.exceptions import ConvergenceWarning


################################################################################################################
# learn_lasso_model: Learns a cross-validation Lasso model from given features
# This function is only used if Intra-MUSiCC is used with the "LearnModel" option
# notes:
# - does NOT normalize X, so X needs to be normalized before sending to function
# - does NOT center Y, so Y needs to be centered before sending to function
################################################################################################################
def learn_lasso_model(cov_train, res_train):

    num_cv = 5
    k_fold = cross_validation.KFold(len(res_train), n_folds=num_cv, shuffle=True)

    best_validation_rsqr = np.zeros((num_cv,1))
    best_validation_alpha = np.zeros((num_cv,1))

    # iterate for all internal cross-validations to learn the best alpha
    for inner_k, (inner_train, inner_validation) in enumerate(k_fold):
        cov_inner_train = cov_train[inner_train, :]
        cov_inner_validation = cov_train[inner_validation, :]
        response_inner_train = res_train[inner_train]
        response_inner_validation = res_train[inner_validation]

        lpath = linear_model.lars_path(cov_inner_train, response_inner_train)
        lpath_alphas = lpath[0]
        lpath_coefs = lpath[2]  # for enet_path = 1
        num_alphas = len(lpath_alphas)

        prediction_validation = np.dot(lpath_coefs.transpose(), cov_inner_validation.transpose())

        rep_res_val = np.repeat(response_inner_validation, num_alphas).reshape(len(response_inner_validation), num_alphas).transpose()
        rep_mean_val = np.repeat(np.mean(response_inner_validation), len(response_inner_validation)*num_alphas).reshape(len(response_inner_validation), num_alphas).transpose()

        sos_residual = np.sum((prediction_validation - rep_res_val) ** 2, axis=1)
        sos_original = np.sum((rep_res_val - rep_mean_val) ** 2, axis=1)

        rep_validation_rsqr = np.array(1 - (sos_residual / sos_original))

        sorted_ind = np.argsort(rep_validation_rsqr)[::-1]
        best_validation_rsqr[inner_k] = rep_validation_rsqr[sorted_ind[0]]
        best_validation_alpha[inner_k] = lpath_alphas[sorted_ind[0]]

    mean_best_alpha = np.mean(best_validation_alpha)
    mean_best_rsqr = np.mean(best_validation_rsqr)

    # now learn one unified model on the given data using the mean_best_alpha
    lasso = linear_model.Lasso(fit_intercept=True, normalize=False, alpha=mean_best_alpha)
    lasso.fit(cov_train, res_train)

    return lasso, mean_best_rsqr

################################################################################################################


###################################################################################################################
# MAIN FUNCTION
# corrects the given abundance data
###################################################################################################################
def correct_and_normalize(args):

    print("Running MUSiCC...")

    # if verbose, print given options
    if args['verbose']:
        print("Input: " + args['input_file'])
        print("Output: " + args['output_file'])
        print("Normalize: " + str(args['musicc_inter']))
        print("Correct: " + args['musicc_intra'])
        print("Compute scores: " + str(args['compute_scores']))

    # set some initial settings for the script
    np.set_printoptions(precision=5,suppress=True, linewidth=200)  # nicer output
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    # get the current directory of the module
    curr_dir_of_module = os.path.split(os.path.realpath(__file__))[0]

    ########################################################
    # start the timer to measure how long it takes to run the module
    t_start = time()
    ########################################################

    ########################################################
    # import the list of Universal single-copy genes (USCG)
    ########################################################
    assert os.path.isfile(curr_dir_of_module + "/data/uscg_76_kegg_min_2313.lst"), "data file of USiCGs is missing"
    ins = open(curr_dir_of_module + "/data/uscg_76_kegg_min_2313.lst", "r")
    uscg = []
    for line in ins:
        uscg.append(line.strip())
    ins.close()
    uscg = set(uscg)

    if args['compute_scores']:
        # import the semi-USCGs list
        assert os.path.isfile(curr_dir_of_module + "/data/semi_uscg_72_kegg_min_2148_max_2313.lst"), "data file of semi-USiCGs is missing"
        ins = open(curr_dir_of_module + "/data/semi_uscg_72_kegg_min_2148_max_2313.lst", "r")
        semi_uscg = []
        for line in ins:
            semi_uscg.append(line.strip())
        ins.close()
        semi_uscg = set(semi_uscg)

        # import the correlog clusters lists
        assert os.path.isfile(curr_dir_of_module + "/data/Correlog_clusters_genes_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab"), "data file of correlogs is missing"
        ins = open(curr_dir_of_module + "/data/Correlog_clusters_genes_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab", "r")
        correlog_clusters = []
        for line in ins:
            line_arr = line.strip().split("\t")
            correlog_clusters.append(line_arr[1].split(":"))
        ins.close()
        number_of_correlog_clusters = len(correlog_clusters)

    ########################################################

    ########################################################
    # import the data file, KO vs. Samples
    ########################################################
    print("Loading data using pandas module...")

    assert os.path.isfile(args['input_file']), "abundance data input file is missing"

    if args['input_format'] == 'biom':  # input in biom format
        print("converting from biom format...")
        temporary_name = base64.urlsafe_b64encode(uuid.uuid4().bytes).replace('=', '')
        os.system("biom convert -i " + args['input_file'] + "-o " + temporary_name + " -b")
        print("Done.")

        ko_abun_data = pd.read_table(temporary_name, index_col=0, dtype={0: str})

        #1.0 version: ins = open(temporary_name, "r")
        #1.0 version: delimiter = "\t"
    elif args['input_format'] == 'csv':  # csv format
        ko_abun_data = pd.read_table(args['input_file'], index_col=0, dtype={0: str}, sep=',')
        #1.0 version: ins = open(args['input_file'], "r")
        #1.0 version: delimiter = ","

    else:   # tab format
        ko_abun_data = pd.read_table(args['input_file'], index_col=0, dtype={0: str})

        #1.0 version: ins = open(args['input_file'], "r")
        #1.0 version: delimiter = "\t"

    genes = ko_abun_data.index.values
    samples = ko_abun_data.columns.values
    abun = ko_abun_data.values

    # 1.0 version:
    #abun = []
    #genes = []
    #row_counter = 0
    #for line in ins:
    #    line_arr = line.strip().split(delimiter)
    #    if len(line_arr[0]) == 0 or line_arr[0][0] == '#':
    #        continue
    #    if row_counter == 0:
    #        samples = line_arr[1:]
    #    else:
    #        genes.append(line_arr[0])
    #        abun.append(line_arr[1:])
    #        if not len(line_arr[1:]) == len(samples):
    #            print("Error: number of values for gene " + str(line_arr[0]) + " (" + str(len(line_arr)) + ")"
    #                  " does not match number of samples " + "(" + str(len(samples)) + ")"
    #                  ", possibly because of missing row header for samples (top left header)")
    #            exit()
    #    row_counter += 1
    #ins.close()
    #genes = np.array(genes)
    #abun = np.array(abun, dtype=np.float64)
    #samples = np.array(samples)

    if args['input_format'] == 'biom':
        os.system("rm " + temporary_name)

    # now sort by genes
    genes_sort_ind = np.array(sorted(range(len(genes)), key=lambda k: genes[k]))
    genes = genes[genes_sort_ind]
    abun = abun[genes_sort_ind]

    num_of_samples = len(samples)
    num_of_genes = len(genes)
    if args['verbose']:
        print(str(num_of_samples) + " samples and " + str(num_of_genes) + " genes")

    # intersect genes with USCGs to find out their indices
    uscg_ind = [i for i, item in enumerate(genes) if item in uscg]
    print("Done.")
    ########################################################

    ################################################################
    # if option selected, correct the abundance per sample by a model based on USiCG
    ################################################################
    if args['musicc_intra'] != 'None':
        print("Performing MUSiCC Correction...")

        if args['musicc_intra'] == 'use_generic': # use generic model
            # load the learned weights from file
            model__feature_names = []
            model__sample_names = []
            model__intercept_vals = []
            model__coef_vals = []
            row_counter = 0 # counter and reference
            assert os.path.isfile(curr_dir_of_module + "/data/Final_Betas_ALL_SAMPLES_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab"), "data file of learned models is missing"
            ins = open(curr_dir_of_module + "/data/Final_Betas_ALL_SAMPLES_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab", "r")
            for line in ins:
                vals = line.strip().split("\t")
                # check if first line
                if (row_counter == 0):
                    model__feature_names = vals[1:]
                else:
                    model__sample_names.append(vals[0])
                    model__intercept_vals.append(vals[1])
                    model__coef_vals.append(vals[2:])
                row_counter += 1

            ins.close()

            # convert to arrays
            model__feature_names = np.array(model__feature_names)
            model__sample_names = np.array(model__sample_names)
            model__intercept_vals = np.array(model__intercept_vals, dtype=np.float64)
            model__coef_vals = np.array(model__coef_vals, dtype=np.float64)

            # compute mean of intercept and mean of coefficients
            model__mean_intercept = np.mean(model__intercept_vals)
            model__mean_coef = np.mean(model__coef_vals, axis=0)
            if args['verbose']:
                print("Generic model intercept:" + str(model__mean_intercept))
                print("Generic model coefficients:" + str(model__mean_coef))

        # load features for the genes
        feature_names = []
        features_kos = []
        features_vals = []
        row_counter = 0 # counter and reference
        assert os.path.isfile(curr_dir_of_module + "/data/Gene_level_features_for_all_KOs_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab"), "data file of gene-level features is missing"
        ins = open(curr_dir_of_module + "/data/Gene_level_features_for_all_KOs_DATA_HMP_STOOL_CLASS_HMP_SAMP_134_KO_76.tab", "r")
        for line in ins:
            vals = line.strip().split("\t")
            # check if first line
            if (row_counter == 0):
                feature_names = vals[1:]
            else:
                features_kos.append(vals[0])
                features_vals.append(vals[1:])

            row_counter += 1

        ins.close()

        # convert to arrays
        feature_names = np.array(feature_names)
        features_kos = np.array(features_kos)
        features_vals = np.array(features_vals, dtype=np.float64)

        #sort features by genes
        featuers_sorting_by_ko = np.array(sorted(range(len(features_kos)), key=lambda k: features_kos[k]))
        features_kos = features_kos[featuers_sorting_by_ko]
        features_vals = features_vals[featuers_sorting_by_ko, :]

        # intersect lists of USCGs between features and abundance
        uscg__inter_features_abundance = np.intersect1d(features_kos, np.intersect1d(genes, np.array(list(uscg))))
        uscg__features_ind_of_intersection = [i for i,item in enumerate(features_kos) if item in uscg__inter_features_abundance]
        uscg__abundance_ind_of_intersection = [i for i,item in enumerate(genes) if item in uscg__inter_features_abundance]

        # intersect lists of ALL GENES between features and abundance
        all_genes__inter_features_abundance = np.intersect1d(features_kos, genes)
        all_genes__features_ind_of_intersection = [i for i,item in enumerate(features_kos) if item in all_genes__inter_features_abundance]
        all_genes__abundance_ind_of_intersection = [i for i,item in enumerate(genes) if item in all_genes__inter_features_abundance]

        if args['compute_scores']:
            # intersect lists of semi-USCGs between features and abundance
            semi_uscg__inter_features_abundance = np.intersect1d(features_kos, np.intersect1d(genes, np.array(list(semi_uscg))))
            semi_uscg__features_ind_of_intersection = [i for i,item in enumerate(features_kos) if item in semi_uscg__inter_features_abundance]
            semi_uscg__abundance_ind_of_intersection = [i for i,item in enumerate(genes) if item in semi_uscg__inter_features_abundance]

            # intersect lists of correlog clusters between features and abundance
            corelog_cluster__inter_features_abundance = []
            corelog_cluster__features_ind_of_intersection = []
            corelog_cluster__abundance_ind_of_intersection = []

            for clus in range(number_of_correlog_clusters):
                corelog_cluster__inter_features_abundance.append(np.intersect1d(features_kos, np.intersect1d(genes, correlog_clusters[clus])))
                corelog_cluster__features_ind_of_intersection.append([i for i,item in enumerate(features_kos) if item in corelog_cluster__inter_features_abundance[clus]])
                corelog_cluster__abundance_ind_of_intersection.append([i for i,item in enumerate(genes) if item in corelog_cluster__inter_features_abundance[clus]])

        ##########################################################################################################
        # Correct abundances per sample across all samples
        ##########################################################################################################

        all_samples_mean_scores = np.zeros((num_of_samples, 1))
        all_samples_mean_scores[:] = np.NaN
        all_samples_final_weights = np.zeros((features_vals.shape[1], num_of_samples))

        if args['compute_scores']:
            all_samples_semi_uscg_scores = np.zeros((num_of_samples, 1))
            all_samples_semi_uscg_scores[:] = np.NaN
            all_samples_correlog_clusters_scores = np.zeros((num_of_samples, number_of_correlog_clusters))
            all_samples_correlog_clusters_scores[:] = np.NaN

        if args['musicc_intra'] == 'learn_model':
            print("Learning sample-specific models")
        else:
            print("Correcting samples using generic model")

        # loop over all samples
        for s in range(num_of_samples):
            sys.stdout.write(".")
            sys.stdout.flush()

            sample_abundance__uscg = np.array(abun[uscg__abundance_ind_of_intersection, s])
            covariates_uscg = features_vals[uscg__features_ind_of_intersection, :]
            final_response = (sample_abundance__uscg / np.mean(sample_abundance__uscg)) - 1.0
            final_covariates = np.nan_to_num(stats.zscore(covariates_uscg))

            # compute prediction for current sample
            if args['musicc_intra'] == 'learn_model':
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', ConvergenceWarning)
                    final_model, all_samples_mean_scores[s] = learn_lasso_model(final_covariates, final_response)

                # compute prediction on all genes
                predicted_correction_for_all_ko = final_model.predict(np.nan_to_num(stats.zscore(features_vals))) + 1

            else:  # use generic model to predict correction
                predicted_correction_for_uscg = np.dot(final_covariates, model__mean_coef) + model__mean_intercept
                predicted_correction_for_all_ko = np.dot(np.nan_to_num(stats.zscore(features_vals)), model__mean_coef) + model__mean_intercept
                sos_residual = np.sum((predicted_correction_for_uscg - (final_response + 1.0)) ** 2)
                sos_original = np.sum(((final_response + 1.0) - np.mean((final_response + 1.0))) ** 2)
                all_samples_mean_scores[s] = 1.0 - (sos_residual / sos_original)

            # set min/max of prediction to the min/max of USCGs (to eliminate outliers in prediction)
            min_correction_uscg = np.min(predicted_correction_for_all_ko[uscg__features_ind_of_intersection])
            max_correction_uscg = np.max(predicted_correction_for_all_ko[uscg__features_ind_of_intersection])
            low_values_indices = predicted_correction_for_all_ko < min_correction_uscg
            predicted_correction_for_all_ko[low_values_indices] = min_correction_uscg
            high_values_indices = predicted_correction_for_all_ko > max_correction_uscg
            predicted_correction_for_all_ko[high_values_indices] = max_correction_uscg

            # apply the correction to the actual abundance array
            abun[all_genes__abundance_ind_of_intersection, s] = abun[all_genes__abundance_ind_of_intersection, s] / predicted_correction_for_all_ko[all_genes__features_ind_of_intersection]

            if args['compute_scores']:  # test prediction on semi-USCGs and clusters to report socres
                sample_abundance__semi_uscg = np.array(abun[semi_uscg__abundance_ind_of_intersection, s])
                covariates_semi_uscg = np.nan_to_num(stats.zscore(features_vals[semi_uscg__features_ind_of_intersection, :]))
                response_semi_uscg = (sample_abundance__semi_uscg / np.mean(sample_abundance__semi_uscg)) - 1.0
                if args['musicc_intra'] == 'learn_model':
                    all_samples_semi_uscg_scores[s] = final_model.score(covariates_semi_uscg, response_semi_uscg)
                else:
                    predicted_correction_for_semi_uscg = np.dot(covariates_semi_uscg, model__mean_coef) + model__mean_intercept
                    sos_residual = np.sum((predicted_correction_for_semi_uscg - (response_semi_uscg + 1.0)) ** 2)
                    sos_original = np.sum(((response_semi_uscg + 1.0) - np.mean((response_semi_uscg + 1.0))) ** 2)
                    all_samples_semi_uscg_scores[s] = 1.0 - (sos_residual / sos_original)

                for clus in range(number_of_correlog_clusters):
                    covariates_clus = np.nan_to_num(stats.zscore(features_vals[corelog_cluster__features_ind_of_intersection[clus], :]))
                    response_clus = (abun[corelog_cluster__abundance_ind_of_intersection[clus], s] / np.mean(abun[corelog_cluster__abundance_ind_of_intersection[clus], s])) - 1
                    if len(response_clus) >= 5 and not np.max(np.isnan(response_clus)):
                        if args['musicc_intra'] == 'learn_model':
                            all_samples_correlog_clusters_scores[s, clus] = final_model.score(covariates_clus, response_clus)
                        else:
                            predicted_correction_for_correlog_clusters = np.dot(covariates_clus, model__mean_coef) + model__mean_intercept
                            sos_residual = np.sum((predicted_correction_for_correlog_clusters - (response_clus + 1.0)) ** 2)
                            sos_original = np.sum(((response_clus + 1.0) - np.mean((response_clus + 1.0))) ** 2)
                            all_samples_correlog_clusters_scores[s, clus] = 1.0 - (sos_residual / sos_original)

        print("Done.")
        # if option selected, aggregate scores from all samples
        if args['compute_scores'] and args['verbose']:
            print("Model performance on various gene sets:")
            print("Median R^2 across samples for all USCG:" + str(np.nanmedian(all_samples_mean_scores)[0]))
            print("Median R^2 across samples for all semi-USCG:" + str(np.nanmedian(all_samples_semi_uscg_scores)[0]))
            print("Number_of_correlog_clusters:" + str(number_of_correlog_clusters))
            print("Median R^2 across samples for all correlog clusters:" + str(np.nanmedian(np.nanmedian(all_samples_correlog_clusters_scores))))

    ################################################################

    ################################################################
    # if option selected, normalize the samples by the median USiCG
    ################################################################
    if args['musicc_inter']:
        print("Performing MUSiCC Normalization...")
        # compute median USCGs per sample
        median_uscg_per_sample = np.median(abun[uscg_ind,:], axis=0)
        if args['verbose']:
            print("median USiCG before MUSiCC = " + str(median_uscg_per_sample))

        # check to see which samples have NO USiCGs at all
        no_zero_samples = np.all(median_uscg_per_sample > 0)
        if not no_zero_samples:
            samples_with_no_usicg = (median_uscg_per_sample == 0)
            print("Warning: The following samples have no Universal Single-copy genes and were converted to NaN - " + str(samples[samples_with_no_usicg]))

        # generate the array of correction by median USCGs
        uscg_median_corrector = np.repeat(median_uscg_per_sample, num_of_genes, axis=0).reshape(num_of_samples, num_of_genes).transpose()

        # perform the correction on given abundance
        abun = abun / uscg_median_corrector
        # convert inf to NaN
        abun[np.isinf(abun)] = np.nan

        if args['verbose']:
            print("median USiCG after MUSiCC = " + str(np.median(abun[uscg_ind,:], axis=0)))

        print("Done.")

    ################################################################################

    ################################################################
    # print corrected abundance to output file
    ################################################################
    output_pd = pd.DataFrame(data=abun, index=genes, columns=samples)
    output_pd.index.name = 'KO'
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore",category=DeprecationWarning)
        if args['output_format'] == 'csv':  # csv format
            output_pd.to_csv(args['output_file'], sep=',', na_rep='NaN')
        elif args['output_format'] == 'tab':  # tab format
            output_pd.to_csv(args['output_file'], sep='\t', na_rep='NaN')
        else:   # biom format
            print("Writing output in biom format...")
            temporary_name = base64.urlsafe_b64encode(uuid.uuid4().bytes).replace('=', '')
            output_pd.to_csv(temporary_name, sep='\t', na_rep='NaN')
            if os.path.isfile(args['output_file']):  # remove file if exists such that biom won't crash
                os.system("rm " + args['output_file'])

            os.system("biom convert -i " + temporary_name + " -o " + args['output_file'] + " --table-type=\"gene table\" --matrix-type=dense")
            os.system("rm " + temporary_name)

    print("Done.")
    ##########################################

    ##########################################
    # print out time spent in module
    t_end = time()
    print('Running time was %.0f seconds.' % (t_end - t_start))
    ##########################################

