#==========================================================#
# Estimate beach slopes from CoastSat 2D shorelines
#==========================================================#

# Kilian Vos WRL 2019

#%% 1. Initial settings

import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz
import pickle
import SDS_slope

# plotting params
plt.style.use('default')
plt.rcParams['font.size'] = 14
plt.rcParams['xtick.labelsize'] = 12
plt.rcParams['ytick.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['legend.fontsize'] = 1

#%% 2. Load 2D shorelines and transects

# load the sitename_output.pkl generated by CoastSat
sitename = 'NARRA'
with open(os.path.join('example_data', sitename + '_output' + '.pkl'), 'rb') as f:
    output = pickle.load(f) 
    
# load the 2D transects from geojson file
geojson_file = os.path.join(os.getcwd(), 'example_data', 'NARRA_transects.geojson')
transects = SDS_slope.transects_from_geojson(geojson_file)

# remove S2 shorelines (the slope estimation algorithm needs only Landsat)
if 'S2' in output['satname']:
    idx_S2 = np.array([_ == 'S2' for _ in output['satname']])
    for key in output.keys():
        output[key] = [output[key][_] for _ in np.where(~idx_S2)[0]]

# remove duplicates 
output = SDS_slope.remove_duplicates(output)
# remove shorelines from images with poor georeferencing (RMSE > 10 m)
output = SDS_slope.remove_inaccurate_georef(output, 10)

# plot shorelines and transects
fig,ax = plt.subplots(1,1,figsize=[12,  8])
fig.set_tight_layout(True)
ax.axis('equal')
ax.set(xlabel='Eastings', ylabel='Northings', title=sitename)
ax.grid(linestyle=':', color='0.5')
for i in range(len(output['shorelines'])):
    coords = output['shorelines'][i]
    date = output['dates'][i]
    ax.plot(coords[:,0], coords[:,1], '.', label=date.strftime('%d-%m-%Y'))
for key in transects.keys():
    ax.plot(transects[key][:,0],transects[key][:,1],'k--',lw=2)
    ax.text(transects[key][-1,0], transects[key][-1,1], key)

# a more robust method to compute intersection is needed here to avoid outliers
# as these can affect the slope detection algorithm
settings_transects = { # parameters for shoreline intersections
                      'along_dist':         25,             # along-shore distance to use for intersection
                      'max_std':            15,             # max std for points around transect
                      'max_range':          30,             # max range for points around transect
                      'min_val':            -100,           # largest negative value along transect (landwards of transect origin)
                      # parameters for outlier removal
                      'nan/max':            'auto',         # mode for removing outliers ('auto', 'nan', 'max')
                      'prc_std':            0.1,            # percentage to use in 'auto' mode to switch from 'nan' to 'max'
                      'max_cross_change':   40,        # two values of max_cross_change distance to use
                      }
# compute intersections [advanced version]
cross_distance = SDS_slope.compute_intersection(output, transects, settings_transects) 
# remove outliers [advanced version]
cross_distance = SDS_slope.reject_outliers(cross_distance,output,settings_transects)        
# plot time-series
SDS_slope.plot_cross_distance(output['dates'],cross_distance)
    
# slope estimation settings
days_in_year = 365.2425
seconds_in_day = 24*3600
settings_slope = {'slope_min':        0.035,
                  'slope_max':        0.2, 
                  'delta_slope':      0.005,
                  'date_range':       [1999,2020],            # range of dates over which to perform the analysis
                  'n_days':           8,                      # sampling period [days]
                  'n0':               50,                     # for Nyquist criterium
                  'freqs_cutoff':     1./(seconds_in_day*30), # 1 month frequency
                  'delta_f':          100*1e-10,              # deltaf for buffer around max peak                                           # True to save some plots of the spectrums
                  }
settings_slope['date_range'] = [pytz.utc.localize(datetime(settings_slope['date_range'][0],5,1)),
                                pytz.utc.localize(datetime(settings_slope['date_range'][1],1,1))]
beach_slopes = SDS_slope.range_slopes(settings_slope['slope_min'], settings_slope['slope_max'], settings_slope['delta_slope'])

# clip the dates between 1999 and 2020 as we need at least 2 Landsat satellites 
idx_dates = [np.logical_and(_>settings_slope['date_range'][0],_<settings_slope['date_range'][1]) for _ in output['dates']]
dates_sat = [output['dates'][_] for _ in np.where(idx_dates)[0]]
for key in cross_distance.keys():
    cross_distance[key] = cross_distance[key][idx_dates]

#%% 3. Tide levels
    
# Option 1. if FES2014 global tide model is setup
import pyfes
filepath = r'C:\Users\Kilian\OneDrive - UNSW\fes-2.9.1-Source\data\fes2014'
config_ocean = os.path.join(filepath, 'ocean_tide_Kilian.ini')
config_ocean_extrap =  os.path.join(filepath, 'ocean_tide_extrapolated_Kilian.ini')
config_load =  os.path.join(filepath, 'load_tide_Kilian.ini')  
ocean_tide = pyfes.Handler("ocean", "io", config_ocean)
load_tide = pyfes.Handler("radial", "io", config_load)

# coordinates of the location (always select a point 1-2km offshore from the beach)
coords = [151.332209, -33.723772]
# get tide time-series with 15 minutes intervals
time_step = 15*60
dates_fes, tide_fes = SDS_slope.compute_tide(coords,settings_slope['date_range'],
                                                   time_step,ocean_tide,load_tide)
# get tide level at time of image acquisition
tide_sat = SDS_slope.compute_tide_dates(coords, dates_sat, ocean_tide, load_tide)

# plot tide time-series
fig, ax = plt.subplots(1,1,figsize=(12,3), tight_layout=True)
ax.set_title('Sub-sampled tide levels')
ax.grid(which='major', linestyle=':', color='0.5')
ax.plot(dates_fes, tide_fes, '-', color='0.6')
ax.plot(dates_sat, tide_sat, '-o', color='k', ms=4, mfc='w',lw=1)
ax.set_ylabel('tide level [m]')
ax.set_ylim(SDS_slope.get_min_max(tide_fes))

# Option 2. otherwise load tide levels associated with "dates_sat" from a file
# with open(os.path.join('example_data', sitename + '_tide' + '.pkl'), 'rb') as f:
#     tide_data = pickle.load(f) 
# tides_sat = tide_data['tide']

# plot time-step distribution
t = np.array([_.timestamp() for _ in dates_sat]).astype('float64')
delta_t = np.diff(t)
fig, ax = plt.subplots(1,1,figsize=(12,3), tight_layout=True)
ax.grid(which='major', linestyle=':', color='0.5')
bins = np.arange(np.min(delta_t)/seconds_in_day, np.max(delta_t)/seconds_in_day+1,1)-0.5
ax.hist(delta_t/seconds_in_day, bins=bins, ec='k', width=1);
ax.set(xlabel='timestep [days]', ylabel='counts',
       xticks=settings_slope['n_days']*np.arange(0,20),
       xlim=[0,50], title='Timestep distribution');

# find tidal peak frequency
settings_slope['freqs_max'] = SDS_slope.find_tide_peak(dates_sat,tide_sat,settings_slope)

#%% 4. Estimate beach slopes along the transects

slope_est = dict([])
for key in cross_distance.keys():
    # remove NaNs
    idx_nan = np.isnan(cross_distance[key])
    dates = [dates_sat[_] for _ in np.where(~idx_nan)[0]]
    tide = tide_sat[~idx_nan]
    composite = cross_distance[key][~idx_nan]
    # apply tidal correction
    tsall = SDS_slope.tide_correct(composite,tide,beach_slopes)
    SDS_slope.plot_spectrum_all(dates,composite,tsall,settings_slope)
    slope_est[key] = SDS_slope.integrate_power_spectrum(dates,tsall,settings_slope)
    print('Beach slope at transect %s: %.3f'%(key, slope_est[key]))