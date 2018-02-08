from __future__ import division
from __future__ import print_function
from builtins import str
from builtins import range
from builtins import object
import time
import os
import copy
import pandas as pd
import numpy as np
import seaborn as sns
import deepdish as dd
import matplotlib.pyplot as plt
from scipy.stats import zscore
from .helpers import filter_elecs, get_corrmat, r2z, z2r, rbf, expand_corrmat_fit, expand_corrmat_predict,\
    near_neighbor, timeseries_recon, count_overlapping
from .brain import Brain


class Model(object):
    """
    supereeg model and associated locations

    This class holds your supereeg model.  To create an instance, pass a list
    of brain objects and the model will be generated from those brain objects.
    Alternatively, you can bypass creating a new model by passing numerator,
    denominator and n_subs (see parameters for details).  Additionally,
    you can include a meta dictionary with any other information that you want
    to save with the model.

    Parameters
    ----------

    data : list
        A list of supereeg.Brain objects used to create the model

    locs : pandas.DataFrame
        MNI coordinate (x,y,z) by number of electrode df containing electrode locations

    template : filepath
        Path to a template nifti file used to set model locations

    numerator : Numpy.ndarray
        (Optional) A locations x locations matrix comprising the sum of the zscored
        correlation matrices over subjects.  If used, must also pass denominator,
        locs and n_subs. Otherwise, numerator will be computed from the brain
        object data.

    denominator : Numpy.ndarray
        (Optional) A locations x locations matrix comprising the sum of the number of
        subjects contributing to each matrix cell. If used, must also pass numerator,
        locs and n_subs. Otherwise, denominator will be computed from the brain
        object data.

    n_subs : int
        The number of subjects used to create the model.  Required if you pass
        numerator/denominator.  Otherwise computed automatically from the data.

    meta : dict
        Optional dict containing whatever you want

    date created : str
        Time created


    Attributes
    ----------

    numerator : Numpy.ndarray
        A locations x locations matrix comprising the sum of the zscored
        correlation matrices over subjects

    denominator : Numpy.ndarray
        A locations x locations matrix comprising the sum of the number of
        subjects contributing to each matrix cell

    n_subs : int
        Number of subject used to create the model


    Returns
    ----------
    model : supereeg.Model instance
        A model that can be used to infer timeseries from unknown locations

    """

    def __init__(self, data=None, locs=None, template=None,
                 measure='kurtosis', threshold=10, numerator=None, denominator=None,
                 n_subs=None, meta=None, date_created=None):

        # if all of these fields are not none, shortcut the model creation
        if all(v is not None for v in [numerator, denominator, locs, n_subs]):

            # numerator
            self.numerator = numerator

            # denominator
            self.denominator = denominator

            # if locs arent already a df, turn them into df
            if isinstance(locs, pd.DataFrame):
                self.locs = locs
            else:
                self.locs = pd.DataFrame(locs, columns=['x', 'y', 'z'])

            # number of subjects
            self.n_subs = n_subs

        else:

            # get locations from template, or from locs arg
            if locs is None:

                if template is None:
                    template = os.path.dirname(os.path.abspath(__file__)) + '/data/gray_mask_20mm_brain.nii'

                # load in template file
                from .load import load_nifti

                bo = load_nifti(template)

                # get locations from template
                self.locs = pd.DataFrame(bo.get_locs(), columns=['x', 'y', 'z'])

            else:

                # otherwise, create df from locs passed as arg
                self.locs = pd.DataFrame(locs, columns=['x', 'y', 'z'])

            # initialize numerator
            numerator = np.zeros((self.locs.shape[0], self.locs.shape[0]))

            # initialize denominator
            denominator = np.zeros((self.locs.shape[0], self.locs.shape[0]))

            # turn data into a list if its a single subject
            if type(data) is not list:
                data = [data]

            # loop over brain objects
            for bo in data:

                # filter bad electrodes
                bo = filter_elecs(bo, measure=measure, threshold=threshold)

                # get subject-specific correlation matrix
                sub_corrmat = get_corrmat(bo)

                # convert diag to zeros
                np.fill_diagonal(sub_corrmat, 0)

                # z-score the corrmat
                sub_corrmat_z = r2z(sub_corrmat)

                # get rbf weights
                sub_rbf_weights = rbf(self.locs, bo.locs)

                #  get subject expanded correlation matrix
                num_corrmat_x, denom_corrmat_x = expand_corrmat_fit(sub_corrmat_z, sub_rbf_weights)

                # add in new subj data to numerator
                numerator += num_corrmat_x

                # add in new subj data to denominator
                denominator += denom_corrmat_x

            # attach numerator
            self.numerator = numerator

            # attach denominator
            self.denominator = denominator

            # attach number of subjects
            self.n_subs = len(data)

        # number of electrodes
        self.n_locs = self.locs.shape[0]

        # date created
        if not date_created:
            self.date_created = time.strftime("%c")
        else:
            self.date_created = date_created

        # meta
        self.meta = meta


    def predict(self, bo, nearest_neighbor=True, match_threshold='auto', force_update=False, kthreshold=10):
        """
        Takes a brain object and a 'full' covariance model, fills in all
        electrode timeseries for all missing locations and returns the new brain object

        Parameters
        ----------

        bo : Brain data object or a list of Brain objects
            The brain data object that you want to predict

        nearest_neighbor : True
            Default finds the nearest voxel for each subject's electrode location and
            uses that as revised electrodes location matrix in the prediction.

        match_threshold : 'auto' or int

            auto: if match_threshold auto, ignore all electrodes whose distance from the nearest matching voxel is
            greater than the maximum voxel dimension

            If value is greater than 0, inlcudes only electrodes that are within that distance of matched voxel

        force_update : False
            If True, will update model with patient's correlation matrix.

        kthreshold : 10 or int
            Kurtosis threshold

        Returns
        ----------

        bo_p : Brain data object
            New brain data object with missing electrode locations filled in

        """
        if nearest_neighbor:
            # if match_threshold auto, ignore all electrodes whose distance from the nearest matching voxel is
            # greater than the maximum voxel dimension
            bo = near_neighbor(bo, self, match_threshold=match_threshold)

        # filter bad electrodes
        bo = filter_elecs(bo, measure='kurtosis', threshold=kthreshold)

        # if force_update is True it will update the model with subject's correlation matrix
        if force_update:

            # get subject-specific correlation matrix
            sub_corrmat = get_corrmat(bo)

            # fill diag with zeros
            np.fill_diagonal(sub_corrmat, 0) # <- possible failpoint

            # z-score the corrmat
            sub_corrmat_z = r2z(sub_corrmat)

            # get rbf weights
            sub_rbf_weights = rbf(self.locs, bo.locs)

            #  get subject expanded correlation matrix
            num_corrmat_x, denom_corrmat_x = expand_corrmat_fit(sub_corrmat_z, sub_rbf_weights)

            # add in new subj data
            with np.errstate(invalid='ignore'):
                model_corrmat_x = np.divide(np.add(self.numerator, num_corrmat_x), np.add(self.denominator, denom_corrmat_x))

        else:

            model_corrmat_x = np.divide(self.numerator,self.denominator)

        # find overlapping locations
        bool_mask = count_overlapping(self, bo)

        # get model indices where subject locs overlap with model locs
        #bool_mask = np.sum([(self.locs == y).all(1) for idy, y in bo.locs.iterrows()], 0).astype(bool)

        # if model locs is a subset of patient locs, nothing to reconstruct
        assert not all(bool_mask),"model is a complete subset of patient locations"

        # indices of the mask (where there is overlap
        joint_model_inds = np.where(bool_mask)[0]

        # if there is no overlap, expand the model and predict at unknown locs
        if not any(bool_mask):

            # expanded rbf weights
            model_rbf_weights = rbf(pd.concat([self.locs, bo.locs]), self.locs)

            # get model expanded correlation matrix
            num_corrmat_x, denom_corrmat_x = expand_corrmat_predict(model_corrmat_x, model_rbf_weights)

            # divide the numerator and denominator
            with np.errstate(invalid='ignore'):
                model_corrmat_x = np.divide(num_corrmat_x, denom_corrmat_x)

            # label locations as reconstructed or observed
            loc_label = ['reconstructed'] * len(self.locs) + ['observed'] * len(bo.locs)

            # grab the locs
            perm_locs = self.locs.append(bo.locs)

        # else if all of the subject locations are in the set of model locations
        elif sum(bool_mask) == bo.locs.shape[0]:

            # permute the correlation matrix so that the inds to reconstruct are on the right edge of the matrix
            perm_inds = sorted(set(range(self.locs.shape[0])) - set(joint_model_inds)) + sorted(set(joint_model_inds))
            model_corrmat_x = model_corrmat_x[:, perm_inds][perm_inds, :]

            # label locations as reconstructed or observed
            loc_label = ['reconstructed'] * (len(self.locs)-len(bo.locs)) + ['observed'] * len(bo.locs)

            # grab permuted locations

            perm_locs = self.locs.iloc[perm_inds]

        # else if some of the subject and model locations overlap
        elif sum(bool_mask) != bo.locs.shape[0]:

            # get subject indices where subject locs do not overlap with model locs
            bool_bo_mask= np.sum([(bo.locs == y).all(1) for idy, y in self.locs.iterrows()], 0).astype(bool)
            disjoint_bo_inds = np.where(~bool_bo_mask)[0]

            # permute the correlation matrix so that the inds to reconstruct are on the right edge of the matrix
            perm_inds = sorted(set(range(self.locs.shape[0])) - set(joint_model_inds)) + sorted(set(joint_model_inds))
            model_permuted = model_corrmat_x[:, perm_inds][perm_inds, :]

            # permute the model locations (important for the rbf calculation later)
            model_locs_permuted = self.locs.iloc[perm_inds]

            # permute the subject locations arranging them
            bo_perm_inds = sorted(set(range(bo.locs.shape[0])) - set(disjoint_bo_inds)) + sorted(set(disjoint_bo_inds))
            sub_bo = bo.locs.iloc[disjoint_bo_inds]
            bo.locs = bo.locs.iloc[bo_perm_inds]
            bo.data = bo.data[bo_perm_inds]

            # permuted indices for unknown model locations
            perm_inds_unknown = sorted(set(range(self.locs.shape[0])) - set(joint_model_inds))

            # expanded rbf weights
            #model_rbf_weights = rbf(pd.concat([model_locs_permuted, bo.locs]), model_locs_permuted)
            model_rbf_weights = rbf(pd.concat([model_locs_permuted, sub_bo]), model_locs_permuted)

            # get model expanded correlation matrix
            num_corrmat_x, denom_corrmat_x = expand_corrmat_predict(model_permuted, model_rbf_weights)

            # divide the numerator and denominator
            with np.errstate(invalid='ignore'):
                model_corrmat_x = np.divide(num_corrmat_x, denom_corrmat_x)

            # add back the permuted correlation matrix for complete subject prediction
            model_corrmat_x[:model_permuted.shape[0], :model_permuted.shape[0]] = model_permuted

            # label locations as reconstructed or observed
            loc_label = ['reconstructed'] * len(self.locs.iloc[perm_inds_unknown]) + ['observed'] * len(bo.locs)

            ## unclear if this will return too many locations
            perm_locs = self.locs.iloc[perm_inds_unknown].append(bo.locs)

        #convert from z to r
        model_corrmat_x = z2r(model_corrmat_x)

        # convert diagonals to zeros
        np.fill_diagonal(model_corrmat_x, 0)

        # timeseries reconstruction
        reconstructed = timeseries_recon(bo, model_corrmat_x)

        # join reconstructed and known activity
        activations = np.hstack((reconstructed, zscore(bo.data.as_matrix())))

        # return all data
        return Brain(data=activations, locs=perm_locs, sessions=bo.sessions,
                    sample_rate=bo.sample_rate, label=loc_label)


    def update(self, data, measure='kurtosis', threshold=10):
        """
        Update a model with new data.

        Parameters
        ----------

        data : Brain object, list of Brain objects, Model object, or list of Model objects
            New subject data

        measure : kurtosis
            Measure for filtering electrodes.  Only option currently supported is kurtosis.

        threshold : 10 or int
            Kurtosis threshold

        Returns
        ----------

        model : Model object
            A new updated model object

        """

        m = copy.deepcopy(self)

        numerator = m.numerator
        denominator = m.denominator
        n_subs = m.n_subs

        if type(data) is not list:
            data = [data]

        # loop over brain objects
        for bo in data:

            # filter bad electrodes
            bo = filter_elecs(bo, measure=measure, threshold=threshold)

            # get subject-specific correlation matrix
            sub_corrmat = r2z(get_corrmat(bo))

            # get rbf weights
            sub_rbf_weights = rbf(m.locs, bo.locs)

            #  get subject expanded correlation matrix
            num_corrmat_x, denom_corrmat_x = expand_corrmat_fit(sub_corrmat, sub_rbf_weights)

            # set weights equal to zero where the numerator is equal to nan
            denom_corrmat_x[np.isnan(num_corrmat_x)] = 0

            # add in new subj data to numerator
            numerator = np.nansum(np.dstack((numerator, num_corrmat_x)), 2)

            # add in new subj data to denominator
            denominator += denom_corrmat_x

            # add to n_subs
            n_subs+=1

        return Model(numerator=numerator, denominator=denominator,
                     locs=m.locs, n_subs=n_subs)


    def info(self):
        """
        Print info about the model object

        Prints the number of electrodes, number of subjects, date created,
        and any optional meta data.
        """
        print('Number of locations: ' + str(self.n_locs))
        print('Number of subjects: ' + str(self.n_subs))
        print('Date created: ' + str(self.date_created))
        print('Meta data: ' + str(self.meta))

    def plot(self, **kwargs):
        """
        Plot the supereeg model as a correlation matrix

        This function wraps seaborn's heatmap and accepts any inputs that seaborn
        supports.
        """
        corr_mat = z2r(np.divide(self.numerator, self.denominator))
        np.fill_diagonal(corr_mat, 1)
        sns.heatmap(corr_mat, **kwargs)


    def save(self, fname, compression='blosc'):
        """
        Save method for the model object

        The data will be saved as a 'mo' file, which is a dictionary containing
        the elements of a model object saved in the hd5 format using
        `deepdish`.

        Parameters
        ----------

        fname : str
            A name for the file.  If the file extension (.mo) is not specified,
            it will be appended.

        compression : str
            The kind of compression to use.  See the deepdish documentation for
            options: http://deepdish.readthedocs.io/en/latest/api_io.html#deepdish.io.save

        """


        # put geo vars into a dict
        mo = {
            'numerator' : self.numerator,
            'denominator' : self.denominator,
            'locs' : self.locs,
            'n_subs' : self.n_subs,
            'meta' : self.meta,
            'date_created' : self.date_created
        }

        # if extension wasn't included, add it
        if fname[-3:]!='.mo':
            fname+='.mo'

        # save
        dd.io.save(fname, mo, compression=compression)