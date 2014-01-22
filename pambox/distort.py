from __future__ import division
from __future__ import print_function
import numpy as np
import scipy as sp
from itertools import izip
from scipy.io import wavfile
from scipy.signal import lfilter
from pambox import general
from pambox.general import fftfilt
from numpy.fft import fft, ifft


def mix_noise(clean, noise, sent_level, snr=None):
    """Mix a signal signal noise at a given signal-to-noise ratio.

    :x: ndarray, clean signal.
    :noise: ndarray, noise signal.
    :snr: float, signal-to-noise ratio. If ignored, no noise is mixed, i.e.
          clean == mix.
    :returns: tuple, returns the clean signal, the mixture, and the noise
              alone.

    """

    # Pick a random section of the noise
    N = len(clean)
    nNoise = len(noise)
    if nNoise > N:
        startIdx = np.random.randint(nNoise - N)
        noise = noise[startIdx:startIdx + N]

    if snr is not None:
        # Get speech level and set noise level accordingly
        #    clean_level = general.dbspl(clean)
        #    noise = general.setdbspl(noise, clean_level - snr)
        noise = noise / general.rms(noise) * 10 ** ((sent_level - snr) / 20)
        mix = clean + noise
    else:
        mix = clean

    return clean, mix, noise


def phase_jitter(x, a):
    """Apply phase jitter to a signal.

    :x: ndarray, signal.
    :a: float, phase jitter parameter, between 0 and 1.
    :returns: ndarray, processed signal

    """
    N = len(x)
    return x * np.cos(2 * np.pi * a * np.random.random_sample(N))


def reverb(x, rt):
    """@todo: Docstring for reverb.

    :x: @todo
    :rt: @todo
    :returns: @todo

    """
    pass


def spec_sub(x, noise, factor, w=1024/2., padz=1024/2., shift_p=0.5):
    """Apply spectral subtraction to a signal.

    Typical values of the parameters, for a sampling frequency of 44100 Hz
    W = 1024
    padz = 1024; %zero padding (pad with padz/2 from the left and padz/2 from
    the right )Note that (W+padz) is the final frame window and hence the fft
    length (it is normally chose as a power of 2)
    shift_p = 0.5 # %Shift percentage is 50%

    :x: ndarray, signal
    :noise: ndarray, noise
    :factor: float, the over-subtraction factor
    :w: int, frame length
    :padz: int, zero padding (pad with padz/2 from the left and the right)
    :shift_p: float, shift percentage (overlap)
    :returns: tuple of ndarrays, estimate of clean signal and estimate of
              noisy signal.

    """
    wnd = np.hanning(w + 2)  # create hanning window with length = W
    wnd = wnd[1:-1]

    stim = np.vstack((x, noise))

    len_signal = stim.shape[-1]  # Signal length
    shift_p_indexes = np.floor(w * shift_p)
    n_segments = np.floor((len_signal - w) / shift_p_indexes + 1)
    len_segment = w + padz * 2 * shift_p
    y = np.empty((2, n_segments, len_segment))
    # Initialize arrays for spectral subtraction. Use only positive
    # frequencies.
    Y_hat = np.empty((n_segments, len_segment / 2 + 1))
    PN_hat = Y_hat.copy()

    # For each signal
    for k in range(2):
        # CUT THE APPROPRIATE SIGNAL FRAMES
        indexes = np.tile(np.arange(w), (n_segments, 1))
        index_shift = np.arange(n_segments) * shift_p_indexes
        indexes = indexes + index_shift[:, np.newaxis]
        y_tmp = stim[k]
        y_tmp = y_tmp[indexes.astype('int')] * wnd
        # PAD WITH ZEROS
        pad = np.zeros((n_segments, padz / 2))
        y_pad = np.hstack((pad, y_tmp, pad))
        y[k, :, :] = y_pad

    # FREQUENCY DOMAIN

    # signal:
    Y = fft(y[0])
    #YY = Y(1:round(end/2)+1,:); # Half window (exploit the symmetry)
    YY = Y[:, :(len_segment / 2 + 1)]  # Half window (exploit the symmetry)
    YPhase = np.angle(YY)  # Phase
    Y1 = np.abs(YY)  # Spectrum
    Y2 = Y1 ** 2  # Power Spectrum

    #  noise:
    Y_N = fft(y[1])
    YY_N = Y_N[:, :(len_segment / 2 + 1)]  # Half window (exploit the symmetry)
    Y_NPhase = np.angle(YY_N)  # Phase
    Y_N1 = np.abs(YY_N)  # Spectrum
    Y_N2 = Y_N1 ** 2  # Power Spectrum

    # The noise "estimate" is simply the average of the noise power
    # spectral density in the frame:
    P_N = Y_N2.mean(axis=-1)

    Y_hat = Y2 - factor * P_N[:, np.newaxis]     # subtraction
    Y_hat = np.maximum(Y_hat, 0)  # Make the minima equal zero
    PN_hat = Y_N2 - factor * P_N[:, np.newaxis]  # subtraction for noise alone
    #PN_hat = np.maximum(PN_hat, 0)
    PN_hat[Y_hat == 0] = 0

    Y_hat[0:2, :] = 0
    PN_hat[0:2, :] = 0
    # Combining the estimated power spectrum with the original noisy phase,
    # and add the frames using an overlap-add technique
    output_Y = overlap_and_add(np.sqrt(Y_hat), YPhase, (w + padz), shift_p * w)
    output_N = overlap_and_add(np.sqrt(PN_hat.astype('complex')),
                               Y_NPhase, (w + padz), shift_p * w)

    return output_Y, output_N


def overlap_and_add(powers, phases, len_window, shift_size):
    """Reconstruct a signal with the overlap and add method

    :powers: array-like,
    :phases: array-like,
    :len_window: int, window length
    :shift_size: int, shift length. For non overlapping signals, in would
    equal len_frame. For 50% overlapping signals, it would be len_frame/2.
    :returns: array-like, reconstructed time-domain signal

    """
    n_frames, len_frame = powers.shape
    spectrum = powers * np.exp(1j * phases)
    signal = np.zeros(n_frames * shift_size + len_window - shift_size)

    # Create full spectrum, by joining conjugated positive spectrum
    if len_window % 2:
        # Do no duplicate the DC bin
        spectrum = np.hstack((spectrum, np.conj(np.fliplr(spectrum[:, 1:]))))
    else:
        # If odd-numbered, do not duplicated the DC ans FS/2 bins
        spectrum = np.hstack((spectrum,
                              np.conj(np.fliplr(spectrum[:, 1:-1]))))

    signal = np.zeros((n_frames - 1) * shift_size + len_window)

    for i_frame, hop in enumerate(range(0,
                                        len(signal) - int(len_window) + 1,
                                        int(shift_size))):
        signal[hop:hop + len_window] \
            += np.real(ifft(spectrum[i_frame], len_window))
    return signal


class Westermann_crm(object):

    """Applies HRTF and BRIR for a given target and masker distance."""

    def __init__(self):
        """@todo: to be defined1. """
        # Load the binaural impulse responses
        self.dist = np.asarray([0.5, 2, 5, 10])
        self.brir = {}
        for d in self.dist:
            d_str = self._normalize_fname(d)
            fname = '../stimuli/crm/brirs_40k/aud' \
                    + d_str + 'm.wav'
            wav = wavfile.read(fname)
            self.brir[d] = np.array(wav[1].astype('float') / 2. ** 15).T

    def _normalize_fname(self, d):
        if d > 1:
            d_str = str('%d' % d)
        else:
            d_str = str(d).replace('.', '')
        return d_str

    def apply(self, x, m, tdist, mdist):
        """@todo: Docstring for apply.

        :x: N array, mono clean speech signal
        :m: N array, mono masker signal
        :tdist: float, target distance, in meters
        :mdist: float, masker distance, in meters
        :returns: (2xN array, 2xN array), filtered signal and filterd masker

        """

        if tdist not in self.dist or mdist not in self.dist:
            raise ValueError('The distance values are incorrect.')

        # Filter target with BRIR only
        out_x = np.asarray([fftfilt(b, x) for b in self.brir[tdist]])

        # Equalized masker and then apply the BRIR
        if tdist == mdist:
            m = [m, m]
        else:
            # Load the equalization filter
            eqfilt_name = 't' + self._normalize_fname(tdist) + \
                        'm_m' + self._normalize_fname(mdist) + 'm.mat'

            try:
                eqfilt = sp.io.loadmat('../stimuli/crm/eqfilts/' + eqfilt_name,
                                    squeeze_me=True)
            except IOError:
                raise IOError('Cannot file file %s' % '../stimuli/crm/eqfilts/'
                            + eqfilt_name)
            m = [fftfilt(b, m) for b in [eqfilt['br'], eqfilt['bl']]]

        out_m = np.asarray([fftfilt(b, chan) for b, chan
                            in izip(self.brir[mdist], m)])
        return out_x, out_m