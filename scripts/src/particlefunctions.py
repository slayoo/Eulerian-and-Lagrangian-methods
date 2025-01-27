#!/usr/bin/env python
# -*- coding: utf-8 -*-

import numpy as np
from collections import namedtuple

import sys
sys.path.append('.')
from wavefunctions import *
from webernaturaldispersion import weber_natural_dispersion
from oilfunctions import entrainmentrate
from constants import CONST

from numba import njit

###############################
#### Numerical derivatives ####
###############################

def ddz(K, z, t):
    '''
    Numerical derivative of K(z, t).

    This function calculates a numerical partial derivative
    of K(z, t), with respect to z using forward finite difference.

    K: diffusivity as a function of depth (m**2/s)
    z: current particle depth (m)
    t: current time (s)
    '''
    dz = 1e-6
    return (K(z+dz/2, t) - K(z-dz/2, t)) / dz


############################
#### Random walk scheme ####
############################

def correctstep(K, z, t, dt):
    '''
    Solving the corrected equation with the Euler-Maruyama scheme:

    dz = K'(z, t)*dt + sqrt(2K(z,t))*dW

    See Visser (1997) and Gräwe (2011) for details.

    K: diffusivity as a function of depth (m**2/s)
    z: current particle depth (m)
    t: current time (s)
    dt: timestep (s)
    '''
    dW = np.random.normal(loc = 0, scale = np.sqrt(dt), size = z.size)
    dKdz = ddz(K, z, t)
    return z + dKdz*dt + np.sqrt(2*K(z, t))*dW


####################
#### Rise speed ####
####################

@njit
def rise_speed(d, rho):
    '''
    Calculate the rise speed (m/s) of a droplet due to buoyancy.
    This scheme uses Stokes' law at small Reynolds numbers, with
    a harmonic transition to a constant drag coefficient at high
    Reynolds numbers.

    See Johansen (2000), Eq. (14) for details.

    d: droplet diameter (m)
    rho: droplet density (kg/m**3)
    '''
    # Physical constants
    pref  = 1.054       # Numerical prefactor
    nu    = CONST.nu    # Kinematic viscosity of seawater (m**2/s)
    rho_w = CONST.rho_w # Density of seawater (kg/m**3)
    g = CONST.g         # Acceleration of gravity (m/s**2)

    g_    = g*(rho - rho_w) / rho_w
    if g_ == 0.0:
        return 0.0*d
    else:
        w1    = d**2 * g_ / (18*nu)
        w2    = np.sqrt(d*abs(g_)) * pref * (g_/np.abs(g_)) # Last bracket sets sign
        return w1*w2/(w1+w2)


###########################
#### Utility functions ####
###########################

def advect(z, v, dt):
    '''
    Return the rise in meters due to buoyancy, 
    assuming constant speed (at least within a timestep).

    z: current droplet depth (m)
    v: droplet speed, positive downwards (m/s)
    dt: timestep (s)
    '''
    return z + dt*v

def reflect(z, zmax = None):
    '''
    Reflect from surface.
    Depth is positive downwards.

    z: current droplet depth (m)
    '''
    # Reflect from surface
    z = np.abs(z)
    if zmax is not None:
        z = np.where(z > zmax, 2*zmax - z, z)
    return z

def surface(z, d, v):
    '''
    Remove surfaced elements.
    This method shortens the array by removing surfaced particles.

    z: current droplet depth (m)
    d: droplet diameter (m)
    '''
    # Keep only particles at depths greater than 0
    mask = z >= 0.0
    return z[mask], d[mask], v[mask]

def settle(z, arr, zmax):
    '''
    Remove elements that settle to the bottom.
    This method shortens the array by removing settled particles.

    z: current droplet depth (m)
    arr: droplet diameter, settling speed, or other per-particle property
    zmax: Maximal depth
    '''
    # Keep only particles at depths smaller than Zmax
    mask = z <= zmax
    return z[mask], arr[mask]


#######################################
#### Entrainment related functions ####
#######################################


def entrain(z, d, v, Np, dt, windspeed, h, mu, ift, rho):
    '''
    Entrainment of droplets.
    This function calculates the number of particles to submerged,
    finds new depths and droplet sizes for those particles, and
    appends these to the input arrays of depth and droplet size
    for the currently submerged particles.

    Number of particles to entrain is found from the entrainment rate
    due to Li et al. (2017), intrusion depth is calculated according
    to Delvigne and Sveeney (1988) and the droplet size distribution
    from the weber natural dispersion model (Johansen 2015).

    z: current array of particle depths (m)
    d: current array of droplet diameters (m)
    dt: timestep (s)
    windspeed: windspeed (m/s)
    h: oil film thickness (m)
    mu: dynamic viscosity of oil (kg/m/s)
    rho: oil density (kg/m**3)
    ift: oil-water interfacial tension (N/m)

    returns:
    z: array of particle depths with newly entrained particles appended
    d: array of droplet diameters with newly entrained particles appended
    '''

    # if h == 0, there is no surface oil, and hence no entrainment
    if h == 0:
        return z, d, v

    # Significant wave height and peak wave period
    Hs, Tp = jonswap(windspeed)
    # Calculate lifetime from entrainment rate
    tau = 1/entrainmentrate(rho, mu, ift, Hs, Tp, windspeed)

    # Probability for a droplet to be entrained
    p = 1 - np.exp(-dt/tau)
    R = np.random.random(Np - len(z))
    # Number of entrained droplets
    N = np.sum(R < p)
    # According to Delvigne & Sweeney (1988), droplets are distributed
    # in the interval (1.5 - 0.35)*Hs to (1.5 + 0.35)*Hs
    znew = np.random.uniform(low = 2, high = 3.2, size = N)
    # Assign new sizes from Johansen distribution
    sigma = 0.4 * np.log(10)
    D50n  = weber_natural_dispersion(rho, mu, ift, Hs, h)

    D50v  = np.exp(np.log(D50n) + 3*sigma**2)
    dnew  = np.random.lognormal(mean = np.log(D50v), sigma = sigma, size = N)
    vnew  = rise_speed(dnew, rho)
    # Append newly entrained droplets to existing arrays
    z = np.concatenate((z, znew))
    d = np.concatenate((d, dnew))
    v = np.concatenate((v, vnew))
    return z, d, v

