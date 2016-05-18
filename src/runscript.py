# generic runscript for sciclone extract jobs

import sys
import os
import re
import errno
import time
import json

import extract_utility

import mpi_utility

job = mpi_utility.NewParallel()


# =============================================================================
# =============================================================================
# load job and datasets json

input_json_path = sys.argv[1]

if not os.path.isfile(input_json_path):
    sys.exit("runscript.py has terminated : invalid input json path")

input_json_path = os.path.abspath(input_json_path)

input_file = open(input_json_path, 'r')
input_json = json.load(input_file)
input_file.close()

base_dir = os.path.dirname(os.path.abspath(__file__))


qlist = [(input_json['job']['datasets'].index(i), i['qlist'].index(j))
         for i in input_json['job']['datasets'] for j in i['qlist']]


# =============================================================================
# =============================================================================


def tmp_general_init(self):
    pass


def tmp_master_init(self):
    # start job timer
    self.Ts = int(time.time())
    self.T_start = time.localtime()
    print 'Start: ' + time.strftime('%Y-%m-%d  %H:%M:%S', self.T_start)


def tmp_master_process(self, worker_data):
    pass


def tmp_master_final(self):

    # stop job timer
    T_run = int(time.time() - self.Ts)
    T_end = time.localtime()
    print '\n\n'
    print 'Start: ' + time.strftime('%Y-%m-%d  %H:%M:%S', self.T_start)
    print 'End: '+ time.strftime('%Y-%m-%d  %H:%M:%S', T_end)
    print 'Runtime: ' + str(T_run//60) +'m '+ str(int(T_run%60)) +'s'
    print '\n\n'


    Ts2 = int(time.time())
    T_start2 = time.localtime()
    print 'Merge Start: ' + time.strftime('%Y-%m-%d  %H:%M:%S', T_start2)

    merge_obj = extract_utility.MergeObject(input_json,
                                            os.path.dirname(input_json_path))
    merge_obj.build_merge_list()
    merge_obj.run_merge()

    # stop job timer
    T_run2 = int(time.time() - Ts2)
    T_end2 = time.localtime()
    print '\n\n'
    print 'Merge Start: ' + time.strftime('%Y-%m-%d  %H:%M:%S', T_start2)
    print 'Merge End: '+ time.strftime('%Y-%m-%d  %H:%M:%S', T_end2)
    print 'Merge Runtime: ' + str(T_run2//60) +'m '+ str(int(T_run2%60)) +'s'


def tmp_worker_job(self, task_id):

    task = self.task_list[task_id]

    dataset_index = task[0]
    qlist_index = task[1]

    # dataset name
    data_name = input_json['job']['datasets'][dataset_index]['name']

    settings = input_json['job']['datasets'][dataset_index]['settings']
    item = input_json['job']['datasets'][dataset_index]['qlist'][qlist_index]


    # ==================================================

    # inputs (see jobscript_template comments for detailed descriptions
    #   of inputs)
    # * = managed by ExtractObject

    # absolute path of boundary file *
    bnd_absolute = settings['bnd_absolute']

    # boundary name
    bnd_name = settings['bnd_name']

    # folder which contains data (or data file) *
    data_base = settings['data_base']

    # dataset mini_name
    data_mini = settings['data_mini']

    # string containing year information *
    year_string = settings['years']

    # file mask for dataset files *
    file_mask = settings['file_mask']

    # extract type *
    extract_type = settings['extract_type']

    # output folder
    output_base = settings['output_base']


    # ==================================================


    exo = extract_utility.ExtractObject()

    exo.set_vector_path(bnd_absolute)

    exo.set_base_path(data_base)
    exo.set_reliability(settings['reliability'])

    exo.set_years(year_string)

    exo.set_file_mask(file_mask)

    if extract_type == "categorical":
        exo.set_extract_type(extract_type, settings['categories'])
    else:
        exo.set_extract_type(extract_type)


    # ==================================================


    output_dir = (output_base + "/" + bnd_name + "/cache/" +
                  data_name +"/"+ exo._extract_type)

    # creates directories
    try:
        os.makedirs(output_dir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

    # ==================================================


    # generate raster path
    if exo._run_option == "1":
        raster = item[1]
    else:
        raster = exo._base_path +"/"+ item[1]

    # generate output path
    output = (output_dir + "/" + data_mini +"_"+
              ''.join([str(e) for e in item[0]]) +
              exo._extract_options[exo._extract_type])

    # run extract
    print ('Worker ' + str(self.rank) + ' | Task ' + str(task_id) +
           ' - running extract: ' + output)

    run_status, run_statment = exo.run_extract(raster, output)

    if run_status == 0:
        print ('Worker ' + str(self.rank) + ' | Task ' + str(task_id) +
               ' - ' + run_statment)
    else:
        raise Exception(run_statment)

    return 0


# init / run job

job.set_task_list(qlist)

job.set_general_init(tmp_general_init)
job.set_master_init(tmp_master_init)
job.set_master_process(tmp_master_process)
job.set_master_final(tmp_master_final)
job.set_worker_job(tmp_worker_job)

job.run()

