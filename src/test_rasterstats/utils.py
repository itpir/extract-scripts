# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
import sys
import os
import warnings
from rasterio import features
from affine import Affine
from shapely.geometry import box, MultiPolygon
from .io import window_bounds
from numpy import min_scalar_type
import math


DEFAULT_STATS = ['count', 'min', 'max', 'mean']
VALID_STATS = DEFAULT_STATS + \
    ['sum', 'std', 'median', 'majority', 'minority', 'unique', 'range', 'nodata']
#  also percentile_{q} but that is handled as special case

def get_percentile(stat):
    if not stat.startswith('percentile_'):
        raise ValueError("must start with 'percentile_'")
    qstr = stat.replace("percentile_", '')
    q = float(qstr)
    if q > 100.0:
        raise ValueError('percentiles must be <= 100')
    if q < 0.0:
        raise ValueError('percentiles must be >= 0')
    return q


def rasterize_geom(geom, shape, affine, all_touched=False):
    geoms = [(geom, 1)]
    rv_array = features.rasterize(
        geoms,
        out_shape=shape,
        transform=affine,
        fill=0,
        all_touched=all_touched)
    return rv_array


# https://stackoverflow.com/questions/8090229/
#   resize-with-averaging-or-rebin-a-numpy-2d-array/8090605#8090605
def rebin_sum(a, shape, dtype):
    sh = shape[0],a.shape[0]//shape[0],shape[1],a.shape[1]//shape[1]
    return a.reshape(sh).sum(-1, dtype=dtype).sum(1, dtype=dtype)


def rasterize_pctcover_geom(geom, shape, affine, scale=None, all_touched=False):
    """
    """
    if scale is None:
        scale = 10

    min_dtype = min_scalar_type(scale**2)

    pixel_size = affine[0]/scale
    topleftlon = affine[2]
    topleftlat = affine[5]

    new_affine = Affine(pixel_size, 0, topleftlon,
                    0, -pixel_size, topleftlat)

    new_shape = (shape[0]*scale, shape[1]*scale)

    rv_array = rasterize_geom(geom, new_shape, new_affine, all_touched=all_touched)
    rv_array = rebin_sum(rv_array, shape, min_dtype)

    return rv_array.astype('float32') / (scale**2)


def stats_to_csv(stats, file_object=None):
    """Ouput stats to csv string or file.

    Does not work with generator object for stats, must use list.
    If invalid file_object is given, creates a temporary file.
    If writing to file, returns path to file. Otherwise returns
    csv output as string.
    """
    if file_object is None:

        if sys.version_info[0] >= 3:
            from io import StringIO as IO
        else:
            from cStringIO import StringIO as IO

        csv_fh = IO()

    else:
        if isinstance(file_object, file):
            csv_fh = file_object
        else:
            warnings.warn("invalid file object given, generating temp file instead",
                          UserWarning)
            import tempfile
            tmp_file = tempfile.mkstemp()
            csv_fh = open(tmp_file[1], 'w')

    import csv

    keys = set()
    for stat in stats:
        for key in list(stat.keys()):
            keys.add(key)

    fieldnames = sorted(list(keys), key=str)

    csvwriter = csv.DictWriter(csv_fh, delimiter=str(","), fieldnames=fieldnames)
    csvwriter.writerow(dict((fn, fn) for fn in fieldnames))
    for row in stats:
        csvwriter.writerow(row)

    if file_object is None:
        contents = csv_fh.getvalue()
        csv_fh.close()
        return contents
    else:
        abs_path = os.path.abspath(csv_fh)
        csv_fh.close()
        return abs_path


def check_stats(stats, categorical):
    if not stats:
        if not categorical:
            stats = DEFAULT_STATS
        else:
            stats = []
    else:
        if isinstance(stats, str):
            if stats in ['*', 'ALL']:
                stats = VALID_STATS
            else:
                stats = stats.split()
    for x in stats:
        if x.startswith("percentile_"):
            get_percentile(x)
        elif x not in VALID_STATS:
            raise ValueError(
                "Stat `%s` not valid; "
                "must be one of \n %r" % (x, VALID_STATS))

    run_count = False
    if categorical or 'majority' in stats or 'minority' in stats or 'unique' in stats:
        # run the counter once, only if needed
        run_count = True

    return stats, run_count


def remap_categories(category_map, stats):
    def lookup(m, k):
        """ Dict lookup but returns original key if not found
        """
        try:
            return m[k]
        except KeyError:
            return k

    return {lookup(category_map, k): v
            for k, v in stats.items()}


def key_assoc_val(d, func, exclude=None):
    """return the key associated with the value returned by func
    """
    vs = list(d.values())
    ks = list(d.keys())
    key = ks[vs.index(func(vs))]
    return key


def boxify_points(geom, rast):
    """
    Point and MultiPoint don't play well with GDALRasterize
    convert them into box polygons 99% cellsize, centered on the raster cell
    """
    if 'Point' not in geom.type:
        raise ValueError("Points or multipoints only")

    buff = -0.01 * min(rast.affine.a, rast.affine.e)

    if geom.type == 'Point':
        pts = [geom]
    elif geom.type == "MultiPoint":
        pts = geom.geoms
    geoms = []
    for pt in pts:
        row, col = rast.index(pt.x, pt.y)
        win = ((row, row + 1), (col, col + 1))
        geoms.append(box(*window_bounds(win, rast.affine)).buffer(buff))

    return MultiPolygon(geoms)


def get_latitude_scale(lat):
    """get ratio of longitudal measurement at a latitiude relative to equator

    at the equator, the distance between 0 and 0.008993216 degrees
    longitude is very nearly 1km. this allows the distance returned
    by the calc_haversine_distance function when using 0 and 0.008993216
    degrees longitude, with constant latitude, to server as a scale
    of the distance between lines of longitude at the given latitude

    Args
        lat (int, float): a latitude value
    Returns
        ratio (float): ratio of actual distance (km) between two lines of
                       longitude at a given latitude and at the equator,
                       when the distance between those lines at the equator
                       is 1km
    """
    p1 = (0, lat)
    p2 = (0.008993216, lat)
    ratio = calc_haversine_distance(p1, p2)
    return ratio


def calc_haversine_distance(p1, p2):
    """calculate haversine distance between two points

    # formula info
    # https://en.wikipedia.org/wiki/Haversine_formula
    # http://www.movable-type.co.uk/scripts/latlong.html

    Args
        p1: tuple of (longitude, latitude) format containing int or float values
        p2: tuple of (longitude, latitude) format containing int or float values
    Returns
        d (float): haversine distance between given points p1 and p2
    """
    lon1, lat1 = p1
    lon2, lat2 = p2

    # km
    radius = 6371.0

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat/2)**2 + math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) * math.sin(delta_lon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    # km
    d = radius * c

    return d


