#! /usr/bin/env python
#
# util_NRExtrudeOverlapGrid.py
#
#   This takes the whole NR catalog (aligned spin only!) and extrudes it in mtot (only)
#   Comparisons for cutoff are done ONLY using the 'approx' in LAL, for convenience
#
# EXAMPLES
#
#


import argparse
import sys
import numpy as np
import lalsimutils
import lalsimulation as lalsim
import lalframe
import lal
import functools

import effectiveFisher  as eff   # for the mesh grid generation
import PrecessingFisherMatrix   as pcf   # Superior tools to perform overlaps. Will need to standardize with Evans' approach in effectiveFisher.py

from multiprocessing import Pool
try:
    import os
    n_threads = int(os.environ['OMP_NUM_THREADS'])
    print " Pool size : ", n_threads
except:
    n_threads=1
    print " - No multiprocessing - "

try:
	import NRWaveformCatalogManager as nrwf
	hasNR =True
except:
	hasNR=False
try:
    hasEOB=True
    import EOBTidalExternal as eobwf
except:
    hasEOB=False


###
### Load options
###

parser = argparse.ArgumentParser()
# Parameters
parser.add_argument("--mtot-range",default='[50,110]')
parser.add_argument("--grid-cartesian-npts",default=30)
# Cutoff options
parser.add_argument("--match-value", type=float, default=0.01, help="Use this as the minimum match value. Default is 0.01 (i.e., keep almost everything)")
# Overlap options
parser.add_argument("--fisher-psd",type=str,default="SimNoisePSDiLIGOSRD",help="psd name ('eval'). lalsim.SimNoisePSDaLIGOZeroDetHighPower, lalsim.SimNoisePSDaLIGOZeroDetHighPower, lalsimutils.Wrapper_AdvLIGOPsd, .SimNoisePSDiLIGOSRD... ")
parser.add_argument("--psd-file",  help="File name for PSD (assumed hanford). Overrides --fisher-psd if provided")
parser.add_argument("--srate",type=int,default=16384,help="Sampling rate")
parser.add_argument("--seglen", type=float,default=64., help="Default window size for processing. Short for NR waveforms")
parser.add_argument("--fref",type=float,default=0.);
# External grid
parser.add_argument("--external-grid-xml", default=None,help="Inspiral XML file (injection form) for alternate grid")
parser.add_argument("--external-grid-txt", default=None, help="Cartesian grid. Must provide parameter names in header. Exactly like output of code. Last column not used.")
# Base point
parser.add_argument("--inj", dest='inj', default=None,help="inspiral XML file containing the base point.")
parser.add_argument("--event",type=int, dest="event_id", default=None,help="event ID of injection XML to use.")
parser.add_argument("--fmin", default=10,type=float,help="Mininmum frequency in Hz, default is 40Hz to make short enough waveforms. Focus will be iLIGO to keep comutations short")
parser.add_argument("--mass1", default=35,type=float,help="Mass in solar masses")  # 150 turns out to be ok for Healy et al sims
parser.add_argument("--mass2", default=35,type=float,help="Mass in solar masses")
parser.add_argument("--s1z", default=0.1,type=float,help="Spin1z")
#parser.add_argument("--lambda1",default=590,type=float)
#parser.add_argument("--lambda2", default=590,type=float)
parser.add_argument("--eff-lambda", type=float, help="Value of effective tidal parameter. Optional, ignored if not given")
parser.add_argument("--deff-lambda", type=float, help="Value of second effective tidal parameter. Optional, ignored if not given")
parser.add_argument("--lmax", default=2, type=int)
parser.add_argument("--approx",type=str,default="SEOBNRv2")
# Output options
parser.add_argument("--fname", default="overlap-grid", help="Base output file for ascii text (.dat) and xml (.xml.gz)")
parser.add_argument("--verbose", action="store_true",default=False, help="Required to build post-frame-generating sanity-test plots")
parser.add_argument("--save-plots",default=False,action='store_true', help="Write plots to file (only useful for OSX, where interactive is default")
opts=  parser.parse_args()

if opts.verbose:
    True
    #lalsimutils.rosDebugMessagesContainer[0]=True   # enable error logging inside lalsimutils



###
### Define grid overlap functions
###   - Python's 'multiprocessing' module seems to cause process lock
###

Lmax = 2

def eval_overlap(grid,P_list, IP,indx):
#    if opts.verbose: 
#        print " Evaluating for ", indx
    global Lmax
    P2 = P_list[indx]
    T_here = 1./IP.deltaF
    P2.deltaF=1./T_here
#    P2.print_params()
    hf2 = lalsimutils.complex_hoff(P2)
    nm2 = IP.norm(hf2);  hf2.data.data *= 1./nm2
#    if opts.verbose:
#        print " Waveform normalized for ", indx
    ip_val = IP.ip(hfBase,hf2)
    line_out = []
    line_out = list(grid[indx])
    line_out.append(ip_val)
    if opts.verbose:
        print " Answer ", indx, line_out
    return line_out

def evaluate_overlap_on_grid(hfbase,param_names, grid):
    # Validate grid is working: Create a loop and print for each one.
    # WARNING: Assumes grid for mass-unit variables hass mass units (!)
    P_list = []
    for line in grid:
        Pgrid = P.manual_copy()
        # Set attributes that are being changed as necessary, leaving all others fixed
        for indx in np.arange(len(param_names)):
            Pgrid.assign_param(param_names[indx], line[indx])
        P_list.append(Pgrid)
#    print "Length check", len(P_list), len(grid)
    ###
    ### Loop over grid and make overlaps : see effective fisher code for wrappers
    ###
    #  FIXME: More robust multiprocessing implementation -- very heavy!
#    p=Pool(n_threads)
    # PROBLEM: Pool code doesn't work in new configuration.
    grid_out = np.array(map(functools.partial(eval_overlap, grid, P_list,IP), np.arange(len(grid))))
    # Remove mass units at end
    for p in ['mc', 'm1', 'm2', 'mtot']:
        if p in param_names:
            indx = param_names.index(p)
            grid_out[:,indx] /= lal.MSUN_SI
    # Truncate grid so overlap with the base point is > opts.min_match. Make sure to CONSISTENTLY truncate all lists (e.g., the P_list)
    grid_out_new = []
    P_list_out_new = []
    for indx in np.arange(len(grid_out)):
        if grid_out[indx,-1] > opts.match_value:
            grid_out_new.append(grid_out[indx])
            P_list_out_new.append(P_list[indx])
    grid_out = np.array(grid_out_new)
    return grid_out, P_list_out_new



###
### Define base point 
###


# Handle PSD
# FIXME: Change to getattr call, instead of 'eval'
eff_fisher_psd = lalsim.SimNoisePSDiLIGOSRD
if not opts.psd_file:
    #eff_fisher_psd = eval(opts.fisher_psd)
    eff_fisher_psd = getattr(lalsim, opts.fisher_psd)   # --fisher-psd SimNoisePSDaLIGOZeroDetHighPower   now
    analyticPSD_Q=True
else:
    eff_fisher_psd = lalsimutils.load_resample_and_clean_psd(opts.psd_file, 'H1', 1./opts.seglen)
    analyticPSD_Q = False



P=lalsimutils.ChooseWaveformParams()
if opts.inj:
    from glue.ligolw import lsctables, table, utils # check all are needed
    filename = opts.inj
    event = opts.event_id
    xmldoc = utils.load_filename(filename, verbose = True,contenthandler =lalsimutils.cthdler)
    sim_inspiral_table = table.get_table(xmldoc, lsctables.SimInspiralTable.tableName)
    P.copy_sim_inspiral(sim_inspiral_table[int(event)])
else:    
    P.m1 = opts.mass1 *lal.MSUN_SI
    P.m2 = opts.mass2 *lal.MSUN_SI
    P.s1z = opts.s1z
    P.dist = 150*1e6*lal.PC_SI
    if opts.eff_lambda and Psig:
        lambda1, lambda2 = 0, 0
        if opts.eff_lambda is not None:
            lambda1, lambda2 = lalsimutils.tidal_lambda_from_tilde(m1, m2, opts.eff_lambda, opts.deff_lambda or 0)
            Psig.lambda1 = lambda1
            Psig.lambda2 = lambda2

    P.fmin=opts.fmin   # Just for comparison!  Obviously only good for iLIGO
    P.ampO=-1  # include 'full physics'
    if opts.approx:
        P.approx = lalsim.GetApproximantFromString(opts.approx)
        if not (P.approx in [lalsim.TaylorT1,lalsim.TaylorT2, lalsim.TaylorT3, lalsim.TaylorT4]):
            # Do not use tidal parameters in approximant which does not implement them
            print " Do not use tidal parameters in approximant which does not implement them "
            P.lambda1 = 0
            P.lambda2 = 0
    else:
        P.approx = lalsim.GetApproximantFromString("TaylorT4")
P.deltaT=1./16384
P.taper = lalsim.SIM_INSPIRAL_TAPER_START
P.deltaF = 1./opts.seglen #lalsimutils.findDeltaF(P)
P.fref = opts.fref
P.print_params()


print "    -------INTERFACE ------"
hfBase = lalsimutils.complex_hoff(P)
IP = lalsimutils.CreateCompatibleComplexOverlap(hfBase,analyticPSD_Q=analyticPSD_Q,psd=eff_fisher_psd)
nmBase = IP.norm(hfBase)
hfBase.data.data *= 1./nmBase
if opts.verbose:
    print " ------  SIGNAL DURATION ----- "
    print hfBase.data.length*P.deltaT

###
### Load in the NR simulation array metadata
###
P_list_NR = []
for group in nrwf.internal_ParametersAvailable.keys():
    for param in nrwf.internal_ParametersAvailable[group]:
        wfP = nrwf.WaveformModeCatalog(group,param,metadata_only=True)
        wfP.P.deltaT = P.deltaT
        wfP.P.deltaF = P.deltaF
        wfP.P.fmin = P.fmin
#        wfP.P.print_params()
        if wfP.P.SoftAlignedQ():
#            print " Adding aligned sim ", group, param
            wfP.P.approx = lalsim.GetApproximantFromString(opts.approx)  # Make approx consistent and sane
            wfP.P.m2 *= 0.999  # Prevent failure for exactly equal!
            # Satisfy error checking condition for lal
            wfP.P.s1x = 0
            wfP.P.s2x = 0
            wfP.P.s1y = 0
            wfP.P.s2y = 0
            P_list_NR = P_list_NR + [wfP.P]



###
### Define parameter ranges to be changed
###

template_min_freq = opts.fmin
ip_min_freq = opts.fmin



###
### Lay out grid, currently CARTESIAN.   OPTIONAL: Load grid from file
###


# For now, we just extrude in these parameters
param_names = ['mtot', 'eta','s1z','s2z']

mass_range = np.array(eval(opts.mtot_range))*lal.MSUN_SI
mass_grid =np.linspace( mass_range[0],mass_range[1],opts.grid_cartesian_npts)

# Loop over simulations and mass grid
grid = []
for P in P_list_NR:
#    P.print_params()
    for M in mass_grid:
        P.assign_param('mtot', M)
        newline = []
        for param in param_names:
            newline = newline + [P.extract_param(param)]
#        print newline
        grid = grid+[ newline]

print " ---- DONE WITH GRID SETUP --- "
print " grid points # = " ,len(grid)


grid_out, P_list = evaluate_overlap_on_grid(hfBase, param_names, grid)
if len(grid_out)==0:
    print " No points survive...."

###
### Write output to text file:  p1 p2 p3 ... overlap, only including named params
###
headline = ' '.join(param_names + ['ip'])
np.savetxt(opts.fname+".dat", grid_out, header=headline)

###
### Optional: Write grid to XML file (ONLY if using cutoff option)
###
lalsimutils.ChooseWaveformParams_array_to_xml(P_list, fname=opts.fname, fref=P.fref)


###
### Optional: Scatterplot
###
if opts.verbose and len(param_names)==1 and len(grid_out)>0:
    import matplotlib.pyplot as plt
    fig = plt.figure()
    plt.plot(grid_out[:,0], grid_out[:,1])
    plt.show()

if opts.verbose and len(param_names)==2:
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    ax.scatter(grid_out[:,0], grid_out[:,1], grid_out[:,2])
    plt.show()

print " ---- DONE ----"