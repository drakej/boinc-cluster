#!/usr/bin/python3

from ctypes import sizeof
import json
import socket
from collections import OrderedDict
import time
from flask import Flask, render_template, request
from datetime import datetime, timedelta
import client
import configparser

import logging
from flask.logging import default_handler

# Flask's magic create_app pattern
LOGGER = logging.getLogger('boinc-cluster')

LOGGER.addHandler(default_handler)
LOGGER.setLevel(logging.INFO)


def create_app(test_config=None):
    app = Flask(__name__)

    # updateState()

    @app.template_filter('formatbytes')
    def format_bytes(size):
        tera = 1024*1024*1024*1024
        giga = 1024*1024*1024
        mega = 1024*1024
        kilo = 1024
        unit = None
        val = 0.0

        if size >= tera:
            unit = "TB"
            val = size / tera
        elif size >= giga:
            unit = "GB"
            val = size / giga
        elif size >= mega:
            unit = "MB"
            val = size / mega
        elif size >= kilo:
            unit = "KB"
            val = size / kilo
        else:
            unit = "bytes"

        return "%0.2f %s" % (val, unit)

    @app.route('/')
    def index():
        updateStatus()

        updateProjects()
        updateTasks()
        total_unique_projects = 0
        unique_projects = {}

        task_totals_by_status = {}

        for task in TASKS:
            if task['state'] not in task_totals_by_status:
                task_totals_by_status[task['state']] = 1
            else:
                task_totals_by_status[task['state']] += 1

        for project in PROJECTS:
            if project.project_name not in unique_projects:
                unique_projects[project.project_name] = True
                total_unique_projects += 1
        return render_template('./index.html', status=STATUS, tasks=TASKS, projects=PROJECTS, total_unique_projects=total_unique_projects, task_totals_by_status=task_totals_by_status)

    @app.route('/statistics')
    def statistics():
        updateProjects()
        updateStatistics()
        return render_template('./statistics.html', statistics=statsMap)

    @app.route('/computers', methods=['POST', 'GET'])
    def computers():
        updateHosts()
        if request.method == 'POST':
            hosts = request.form.getlist('host')
            run_modes = request.form.getlist('rmode')
            gpu_modes = request.form.getlist('gmode')
            network_modes = request.form.getlist('nmode')

            for host in hosts:
                h_index = hosts.index(host)

                if host in hostConnectionsMap:
                    boinc_client = hostConnectionsMap[host]
                else:
                    boinc_client = client.BoincClient(
                        host=host, passwd=config['hosts'][host])

                    hostConnectionsMap[host] = boinc_client

                    try:
                        boinc_client.connect()
                    except (socket.timeout, OSError) as timeout:
                        LOGGER.info(f"Timeout: {timeout}")

                srm_result = boinc_client.set_run_mode(
                    int(run_modes[h_index]))
                sgm_result = boinc_client.set_gpu_mode(
                    int(gpu_modes[h_index]))
                snm_result = boinc_client.set_network_mode(
                    int(network_modes[h_index]))

                LOGGER.info(f"set_run_mode on {host} result: {srm_result}")
                LOGGER.info(f"set_gpu_mode on {host} result: {sgm_result}")
                LOGGER.info(
                    f"set_network_mode on {host} result: {snm_result}")

            # Ensure we update again since the state changed
            updateHosts()

        updateStatus()
        updateTasks()

        return render_template('./computers.html', hosts=hostMap,
                               status=STATUS,
                               runModes=runModeDescMap,
                               gpuModes=gpuModeDescMap,
                               netModes=netModeDescMap,
                               tasksByHosts=tasksByHostMap)

    def projects():
        updateProjects(cache=False)
        return render_template('./projects.html', projects=PROJECTS)

    @app.route('/tasks')
    def tasks():
        updateState()
        updateTasks()
        return render_template('./tasks.html', tasks=TASKS, hosts=config['hosts'])

    @app.route('/transfers')
    def transfers():
        updateTransfers()
        return render_template('./transfers.html', transfers=transferMap)

    @app.route('/disk')
    def disk():
        updateProjects()
        updateDiskUsage()
        return render_template('./disk.html', disk_usage_summaries=diskUsageMap)

    @app.route('/tasks/live')
    def tasksLive():
        updateState()
        updateTasks()
        return json.dumps({"data": TASKS})

    return app


config = configparser.ConfigParser()

config.read('config.ini')

hostMap = OrderedDict()
projectMap = OrderedDict()
statsMap = OrderedDict()
diskUsageMap = OrderedDict()
transferMap = OrderedDict()
appMap = {}
appVersionMap = {}
workUnitMap = {}
hostConnectionsMap = {}
tasksByHostMap = {}

PROJECTS = []
TASKS = []
STATUS = OrderedDict()

network_status_icon_map = {
    client.NetworkStatus.UNKNOWN: 'fa-question',
    client.NetworkStatus.ONLINE: 'fa-stream',
    client.NetworkStatus.WANT_CONNECTION: 'fa-plug',
    client.NetworkStatus.WANT_DISCONNECT: 'fa-unlink'
}

runModeIconMap = {
    client.RunMode.ALWAYS: 'text-success fa-bolt',
    client.RunMode.AUTO: 'text-success fa-user-cog',
    client.RunMode.NEVER: 'text-secondary fa-power-off'
}

# TODO: Move to client.py
runModeDescMap = {
    client.RunMode.ALWAYS: 'Run always',
    client.RunMode.AUTO: 'Run based on preferences',
    client.RunMode.NEVER: 'Suspend'
}

gpuModeDescMap = {
    client.RunMode.ALWAYS: 'Use GPU always',
    client.RunMode.AUTO: 'Use GPU based on preferences',
    client.RunMode.NEVER: 'Suspend GPU'
}

netModeDescMap = {
    client.RunMode.ALWAYS: 'Network activity always',
    client.RunMode.AUTO: 'Network activity based on preferences',
    client.RunMode.NEVER: 'Suspend network activity'
}


def updateStatus():
    global hostConnectionsMap
    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Timeout: {timeout}")
                continue

        if boincClient.connected:
            host_state = boincClient.get_cc_status()

            LOGGER.debug(f'host_state: {host_state}')

            host_state.task_mode_icon = runModeIconMap[host_state.task_mode]
            host_state.task_mode_desc = runModeDescMap[host_state.task_mode]
            host_state.network_mode_icon = runModeIconMap[host_state.network_mode]
            host_state.network_mode_desc = netModeDescMap[host_state.network_mode]
            host_state.gpu_mode_icon = runModeIconMap[host_state.gpu_mode]
            host_state.gpu_mode_desc = gpuModeDescMap[host_state.gpu_mode]

            host_state.network_status_icon = network_status_icon_map[host_state.network_status]

            STATUS[host] = host_state


def updateProjects():
    global PROJECTS, projectMap, hostConnectionsMap

    PROJECTS = []

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Timeout: {timeout}")
                continue

        if boincClient.connected:
            hostProjects = boincClient.get_projects()

            if hostProjects:
                for project in hostProjects:
                    project.hostname = host

                    statii = []

                    if project.suspended_via_gui:
                        statii.append("Suspended by user")

                    if project.dont_request_more_work:
                        statii.append("Won't get new tasks")

                    if project.ended:
                        statii.append("Project ended - OK to remove")

                    if project.detach_when_done:
                        statii.append("Will remove when tasks done")

                    if project.sched_rpc_pending:
                        statii.append("Scheduler request pending")
                        statii.append(client.RPCReason.name(
                            project.sched_rpc_pending))

                    if project.scheduler_rpc_in_progress:
                        statii.append("Scheduler request in progress")

                    if project.trickle_up_pending:
                        statii.append("Trickle up message pending")

                    if project.min_rpc_time > time.time():
                        statii.append("Communication deferred " +
                                      str(timedelta(seconds=int(project.min_rpc_time - time.time()))))

                    project.status = ', '.join(statii)
                    PROJECTS.append(project)
                    projectMap[project.master_url] = project


def updateState():
    global appMap, workUnitMap, hostConnectionsMap

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        if boincClient.connected:
            stateInfo = boincClient.get_state()

            for app in stateInfo.apps:
                appMap[app.name] = {
                    "user_friendly_name": app.user_friendly_name,
                    "non_cpu_intensive": app.non_cpu_intensive
                }

            for wu in stateInfo.work_units:
                workUnitMap[wu.name] = {
                    "app_name": wu.app_name,
                    "version_num": wu.version_num,
                    "command_line": wu.command_line
                }
        else:
            LOGGER.info(
                f"Connection lost, couldn't update state for host {host}")


def updateHosts():
    global hostMap, hostConnectionsMap

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        if boincClient.connected:
            hostInfo = boincClient.get_host_info()
            gpu = "--"
            if len(hostInfo.coprocs) == 1:
                gpuData = hostInfo.coprocs[0]
                gpu = "%s" % (gpuData.name)
            elif len(hostInfo.coprocs) > 1:
                gpu = ""

                LOGGER.debug(f"Coprocessors: {hostInfo.coprocs}")

                for proc in hostInfo.coprocs:
                    gpu = "%s " % proc.name

            hostMap[host] = {
                'computerID': hostInfo.host_cpid,
                'hostname': hostInfo.domain_name,
                'ncpus': hostInfo.p_ncpus,
                'fpops': hostInfo.p_fpops,
                'processorModel': hostInfo.p_model,
                'processorVendor': hostInfo.p_vendor,
                'productName': hostInfo.product_name,
                'osName': hostInfo.os_name,
                'osVersion': hostInfo.os_version,
                'gpu': gpu,
                'boincVersion': boincClient.version
            }


def updateTasks():
    global TASKS, projectMap, tasksByHostMap, hostConnectionsMap

    updateProjects()

    TASKS = []
    tasksByHostMap = {}

    for host, password in config['hosts'].items():
        hostTasks = []

        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)
            LOGGER.info(f"initiating connection for host {host}")

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        hostTasks = boincClient.get_results()

        tasksByHostMap[host] = {'tasks': len(hostTasks)}

        cc_status = boincClient.get_cc_status()
        LOGGER.info(f"{host}: {len(hostTasks)}")

        for task in hostTasks:
            projectName = "Unknown"

            percent_complete = round(task.fraction_done * 100, 3)
            state = "Ready to start"
            elapsed = task.elapsed_time

            project = projectMap[task.project_url]

            throttled = cc_status.task_suspend_reason & 64

            if task.coproc_missing:
                state = "GPU Missing, "

            if task.state == 0:
                state = "New"
            elif task.state == 1:
                if task.ready_to_report:
                    state = "Download failed"
                else:
                    state = "Downloading"

                    if cc_status.network_suspend_reason:
                        state += " (suspended - %s)" % cc_status.network_suspend_reason
            elif task.state == 2:
                if task.project_suspended_via_gui:
                    state = "Project suspended by user"
                elif task.suspended_via_gui:
                    state = "Task suspended by user"
                elif cc_status.task_suspend_reason and not throttled and task.active_task_state != 1:
                    state = "Suspended - %s" % cc_status.task_suspend_reason
                elif cc_status.gpu_suspend_reason:
                    state = "GPU suspended - %s" % cc_status.gpu_suspend_reason
                elif task.active_task:
                    if task.too_large:
                        state = "Waiting for memory"
                    elif task.needs_shmem:
                        state = "Waiting for shared memory"
                    elif task.scheduler_state == 2:
                        state = "Running"
                        if project and project.non_cpu_intensive:
                            state += " (non-CPU-intensive)"
                    elif task.scheduler_state == 1:
                        state = "Waiting to run"
                    elif task.scheduler_state == 0:
                        state = "Ready to start"
                else:
                    state = "Ready to start"
                if task.scheduler_wait:
                    if task.scheduler_wait_reason:
                        state = "Postponed: %s" % task.scheduler_wait_reason
                    else:
                        state = "Postponed"
                if task.network_wait:
                    state = "Waiting for network access"
            elif task.state == 3:
                state = "Computation error"
            elif task.state == 4:
                if task.ready_to_report:
                    state = "Upload failed"
                else:
                    state = "Uploading"
                    if cc_status.network_suspend_reason:
                        state += " (suspended - %s)" % cc_status.network_suspend_reason
            elif task.state == 6:
                if task.exit_status == 203:
                    state = "Aborted by user"
                elif task.exit_status == 202:
                    state = "Aborted by project"
                elif task.exit_status == 200:
                    state = "Aborted: not started by deadline"
                elif task.exit_status == 196:
                    state = "Aborted: task disk limit exceeded"
                elif task.exit_status == 197:
                    state = "Aborted: run time limit exceeded"
                elif task.exit_status == 198:
                    state = "Aborted: memory limit exceeded"
                else:
                    state = "Aborted"
            else:
                if task.got_server_ack:
                    state = "Acknowledged"
                elif task.ready_to_report:
                    state = "Ready to report"
                else:
                    state = "Error: invalid state '%d'" % task.state

            # if task.active_task_state and task.active_task_state == 1:
            #     state = "Running"
            if task.estimated_cpu_time_remaining == 0:
                percent_complete = 100
                elapsed = task.final_elapsed_time

            resourceString = ""

            if task.resources:
                resourceString = " (%s)" % task.resources

            statusString = "%s%s" % (state, resourceString)

            try:
                projectName = projectMap[task.project_url].project_name
            except KeyError as error:
                LOGGER.error(f"Couldn't find key: {error}")

            deadline = datetime.fromtimestamp(task.report_deadline)

            days = elapsed // 86600
            elapsedLeft = elapsed - days * 86600
            hours = int(elapsedLeft // 3600)
            elapsedLeft -= hours * 3600
            minutes = int(elapsedLeft // 60)
            seconds = int(elapsedLeft - minutes * 60)

            elapsedTime = "%s:%s:%s" % (str(hours).zfill(
                2), str(minutes).zfill(2), str(seconds).zfill(2))

            if days:
                elapsedTime = "%dd %s:%s:%s" % (days, str(hours).zfill(
                    2), str(minutes).zfill(2), str(seconds).zfill(2))

            if task.estimated_cpu_time_remaining:
                days = task.estimated_cpu_time_remaining // 86600
                remainingLeft = task.estimated_cpu_time_remaining - days * 86600
                hours = int(remainingLeft // 3600)
                remainingLeft -= int(hours * 3600)
                minutes = int(remainingLeft // 60)
                seconds = int(remainingLeft - minutes * 60)

                remaining = "%s:%s:%s" % (str(hours).zfill(2), str(
                    minutes).zfill(2), str(seconds).zfill(2))

                if days:
                    remaining = "%dd %s:%s:%s" % (days, str(hours).zfill(
                        2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                remaining = "--"

            app = ""
            friendly_name = ""
            version = 0xdeadbeef

            if task.wu_name in workUnitMap:
                app = workUnitMap[task.wu_name]['app_name']
                version_str = str(workUnitMap[task.wu_name]['version_num'])
                version = '%s.%s' % (
                    version_str[0], version_str[1:])

            if app in appMap:
                friendly_name = f"{appMap[app]['user_friendly_name']} {version}"

                if task.plan_class:
                    friendly_name += f" ({task.plan_class})"

            TASKS.append({
                'hostname': host,
                'projectName': projectName,
                'projectURL': task.project_url,
                'percent': percent_complete,
                'elapsedTime': elapsedTime,
                'deadline': int(deadline.timestamp() * 1000),
                'remaining': remaining,
                'name': task.name,
                'application': friendly_name,
                'status': statusString,
                'state': state
            })


def updateStatistics():
    global statsMap, projectMap

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        if boincClient.connected:
            statistics = boincClient.get_statistics()
            for ps in statistics.project_statistics:
                ps.project = projectMap[ps.master_url]

            statsMap[host] = statistics


def updateDiskUsage():
    global diskUsageMap, projectMap

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        if boincClient.connected:
            disk_usage = boincClient.get_disk_usage()

            usage = {}

            # See boinc/clientgui/ViewResources.cpp for how this was determined
            #
            usage['boinc'] = sum(
                [dup.disk_usage for dup in disk_usage.projects]) + disk_usage.d_boinc
            usage['free'] = disk_usage.d_free
            usage['total'] = disk_usage.d_total
            usage['available'] = disk_usage.d_allowed - usage['boinc']
            usage['not_available'] = usage['free'] - usage['available']
            usage['other'] = usage['total'] - usage['boinc'] - usage['free']
            usage['projects'] = disk_usage.projects

            for project in usage['projects']:
                project.name = projectMap[project.master_url].project_name

            diskUsageMap[host] = usage


def updateTransfers():
    global transferMap

    for host, password in config['hosts'].items():
        if host in hostConnectionsMap:
            boincClient = hostConnectionsMap[host]
        else:
            boincClient = client.BoincClient(host=host, passwd=password)

            hostConnectionsMap[host] = boincClient

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                LOGGER.info(f"Host {host} Timeout: {timeout}")
                continue

        if boincClient.connected:
            transfers = boincClient.get_file_transfers()

            for transfer in transfers:
                transfer

            transferMap[host] = transfers
