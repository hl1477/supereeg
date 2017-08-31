# -*- coding: utf-8 -*-

import pandas as pd
import time
import os
import numpy as np
import pickle
import nibabel as nib
import warnings
from ._helpers.stats import *
from scipy.stats import zscore

class Brain(object):
    """
    Brain data object for the superEEG package

    A brain data object contains a single iEEG subject. To create one, at minimum
    you need data (samples by electrodes), location coordinates in MNI space and
    the sample rate of the data. Additionally, you can include a session id. If
    included, all analyses will be performed within session and then aggregated
    across sessions.  You can also include a meta dict, which can contain any
    other information that might be useful (subject id, recording params, etc).

    Parameters
    ----------

    data : numpy.ndarray
        Samples x electrodes array containing the EEG data

    locs : numpy.ndarray
        MNI coordinate (x,y,z) by electrode array containing electrode locations

    session : numpy.ndarray
        Samples x 1 array containing session identifiers

    sample_rates : float or list of floats
        Sample rate of the data. If different over multiple sessions, this is a
        list

    meta : dict
        Optional dict containing whatever you want

    Attributes
    ----------

    data : Pandas DataFrame
        Samples x electrodes dataframe containing the EEG data

    locs : Pandas DataFrame
        MNI coordinate (x,y,z) by electrode df containing electrode locations

    sessions : Pandas Series
        Samples x 1 array containing session identifiers.  If a singleton is passed,
         a single session will be created.

    sample_rates : float or list of floats
        Sample rate of the data. If different over multiple sessions, this is a
        list

    meta : dict
        Optional dict containing whatever you want

    n_elecs : int
        Number of electrodes

    n_secs : float
        Amount of data in seconds

    n_sessions : int
        Number of sessions

    session_labels : list
        Label for each session

    kurtosis : list of floats
        1 by number of electrode list containing kurtosis for each electrode


    Returns
    ----------

    bo : Brain data object
        Instance of Brain data object containing subject data

    """

    def __init__(self, data=None, locs=None, sessions=None, sample_rate=None, meta=None):

        # convert data to df
        self.data = pd.DataFrame(data)

        # locs
        self.locs = pd.DataFrame(locs, columns=['x', 'y', 'z'])

        # session
        if isinstance(sessions, str) or isinstance(sessions, int):
            self.sessions = pd.Series([sessions for i in range(self.data.shape[0])])
        ### check this out... I'm not sure what this does
        elif sessions is None:
            self.sessions = pd.Series([1 for i in range(self.data.shape[0])])
        else:
            self.sessions = pd.Series(sessions.ravel())

        # sample rate
        if isinstance(sample_rate, list):
            self.sample_rate = sample_rate
        elif isinstance(sessions, list):
            self.sample_rate = [sample_rate for s in self.sessions.values]
        elif sample_rate is None:
            self.sample_rate = [1000 for s in self.sessions.values]
            warnings.warn('No sample rate given.  Setting sample rate to 1000')
        else:
            self.sample_rate = [sample_rate]

        # meta
        self.meta = meta

        # compute attrs
        self.n_elecs = self.data.shape[1]
        self.n_secs = self.data.shape[0]/self.sample_rate[0] # needs to be calculated by sessions
        self.date_created = time.strftime("%c")
        self.n_sessions = len(self.sessions.unique())

        # add kurtosis
        self.kurtosis = kurt_vals(self)

    def info(self):
        """
        Print info about the brain object

        Prints the number of electrodes, recording time, number of recording
        sessions, date created, and any optional meta data.
        """
        print('Number of electrodes: ' + str(self.n_elecs))
        print('Recording time in seconds: ' + str(self.n_secs))
        print('Number of sessions: ' + str(self.n_sessions))
        print('Date created: ' + str(self.date_created))
        print('Meta data: ' + str(self.meta))

    def get_data(self):
        """
        Gets data from brain object
        """
        return self.data.as_matrix()

    def get_zscore_data(self):
        """
        Gets zscored data from brain object
        """
        return zscore(self.data.as_matrix())

    def get_locs(self):
        """
        Gets locations from brain object
        """
        return self.locs.as_matrix()

    def save(self, filepath):
        """
        Save brain object as a pickle


        Parameters
        ----------

        filepath : str
            Path to save the pickled brain, mwuahahahah

        """
        with open(filepath + '.bo', 'wb') as f:
            pickle.dump(self, f)
            print('Brain object saved as pickle.')

    def to_nii(self, filepath=None,
                 template=None):
        """
        Save brain object as a nifti file


        Parameters
        ----------

        filepath : str
            Path to save the nifti file

        template : str
            Path to template nifti file

        Returns
        ----------

        nifti : nibabel.Nifti1Image
            A nibabel nifti image

        """

        if template is None:
            template = os.path.dirname(os.path.abspath(__file__)) + '/data/gray_mask_20mm_brain.nii'

        # load template
        img = nib.load(template)

        # initialize data
        data = np.zeros(tuple(list(img.shape)+[self.data.shape[0]]))

        # convert coords from matrix coords to voxel indices
        R = self.locs.as_matrix()
        S =  img.affine
        locs = pd.DataFrame(np.dot(R-S[:3, 3], np.linalg.inv(S[0:3, 0:3]))).astype(int)

        # loop over data and locations to fill in activations
        for i, row in self.data.iterrows():
            for j, loc in locs.iterrows():
                a,b,c,d = np.array(loc.values.tolist()+[i])
                data[a, b, c, d] = row.loc[j]

        # create nifti object
        nifti = nib.Nifti1Image(data, affine=img.affine)

        # save if filepath
        if filepath:
            nifti.to_filename(filepath)

        return nifti
