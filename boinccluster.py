#!/usr/bin/python3

import json
import socket
from collections import OrderedDict
import time
from flask import Flask, render_template
from datetime import datetime, timedelta
import client
import configparser

#app = Flask(__name__)

# Flask's magic create_app pattern


def create_app(test_config=None):
    app = Flask(__name__)

    updateState()

    @app.template_filter('formatbytes')
    def format_bytes(size):
        tera = 1024*1024*1024*1024
        giga = 1024*1024*1024
        mega = 1024*1024
        kilo = 1024
        unit = None
        val = None

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

        for project in PROJECTS:
            if project.project_name not in unique_projects:
                unique_projects[project.project_name] = True
                total_unique_projects += 1
        return render_template('./index.html', status=STATUS, tasks=TASKS, projects=PROJECTS, total_unique_projects=total_unique_projects)

    @app.route('/statistics')
    def statistics():
        updateProjects()
        updateStatistics()
        return render_template('./statistics.html', statistics=statsMap)

    @app.route('/computers')
    def computers():
        updateHosts()
        return render_template('./computers.html', hosts=hostMap)

    @app.route('/projects')
    def projects():
        updateProjects(cache=False)
        return render_template('./projects.html', projects=PROJECTS)

    @app.route('/tasks')
    def tasks():
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
PROJECTS = []
projectMapPopulated = False
hostMapPopulated = False
statsMapPopulated = False
appMapPopulated = False
appVersionMapPopulated = False
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
    client.RunMode.NEVER: 'text-secondary fa-power-off',
    client.RunMode.UNKNOWN: 'text-info fa-question',
    client.RunMode.RESTORE: 'text-info fa-play-circle'
}


def updateStatus():
    for host, password in config['hosts'].items():
        boinc_client = client.BoincClient(host=host, passwd=password)

        try:
            boinc_client.connect()
        except (socket.timeout, OSError) as timeout:
            print(timeout)
            continue

        if boinc_client.connected:
            host_state = boinc_client.get_cc_status()

            host_state.task_mode_icon = runModeIconMap[host_state.task_mode]
            host_state.network_mode_icon = runModeIconMap[host_state.network_mode]
            host_state.gpu_mode_icon = runModeIconMap[host_state.gpu_mode]

            host_state.network_status_icon = network_status_icon_map[host_state.network_status]

            STATUS[host] = host_state

        boinc_client.disconnect()

# Will only call one time for now to cache project results


def updateProjects(cache=True):
    global projectMapPopulated, PROJECTS, projectMap
    if not projectMapPopulated:
        PROJECTS = []

        for host, password in config['hosts'].items():
            boincClient = client.BoincClient(host=host, passwd=password)

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                print(timeout)
                continue
            if boincClient.connected:
                hostProjects = boincClient.get_projects()

                if hostProjects:
                    for project in hostProjects:
                        project.hostname = host

                        statii = []

                        # if project.hostname == "desktop-jon.drakes.life":
                        #     print(project)

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
            boincClient.disconnect()

        if cache:
            projectMapPopulated = True


def updateState():
    global appMap, workUnitMap, workUnitMapPopulated, appMapPopulated

    if not appMapPopulated:

        for host, password in config['hosts'].items():
            boincClient = client.BoincClient(host=host, passwd=password)

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                print(timeout)
                continue

            if boincClient.connected:
                stateInfo = boincClient.get_state()

                # print(stateInfo)

                for app in stateInfo.apps:
                    appMap[app.name] = {
                        "user_friendly_name": app.user_friendly_name,
                        "non_cpu_intensive": app.non_cpu_intensive
                    }

                appMapPopulated = True

                for wu in stateInfo.work_units:
                    workUnitMap[wu.name] = {
                        "app_name": wu.app_name,
                        "version_num": wu.version_num,
                        "command_line": wu.command_line
                    }

                workUnitMapPopulated = True


def updateHosts():
    global hostMap, hostMapPopulated
    if not hostMapPopulated:
        for host, password in config['hosts'].items():
            boincClient = client.BoincClient(host=host, passwd=password)

            try:
                boincClient.connect()
            except (socket.timeout, OSError) as timeout:
                print(timeout)
                continue

            if boincClient.connected:
                hostInfo = boincClient.get_host_info()
                gpu = "--"
                if len(hostInfo.coprocs) == 1:
                    gpuData = hostInfo.coprocs[0]
                    gpu = "%s" % (gpuData.name)
                elif len(hostInfo.coprocs) > 1:
                    gpu = ""

                    print(hostInfo.coprocs)

                    for proc in hostInfo.coprocs:
                        gpu = "%s " % proc.name

                # print(hostInfo.coprocs)
                print(gpu)

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

                boincClient.disconnect()
        hostMapPopulated = True


def updateTasks():
    global TASKS, projectMap

    updateProjects()

    TASKS = []

    for host, password in config['hosts'].items():
        boincClient = client.BoincClient(host=host, passwd=password)
        hostTasks = []

        try:
            boincClient.connect()

            hostTasks = boincClient.get_results()

            #print("%s: %d" % (host, len(hostTasks)))
        except (socket.timeout, OSError) as timeout:
            print(timeout)
            continue

        for task in hostTasks:
            projectName = "Unknown"

            percent_complete = round(task.fraction_done * 100, 3)
            state = "Ready to start"
            elapsed = task.elapsed_time

            if task.active_task_state and task.active_task_state == 1:
                state = "Running"
            elif task.estimated_cpu_time_remaining == 0:
                percent_complete = 100
                elapsed = task.final_elapsed_time
                state = "Ready to report"

            resourceString = ""

            if task.resources:
                resourceString = " (%s)" % task.resources

            statusString = "%s%s" % (state, resourceString)

            try:
                projectName = projectMap[task.project_url].project_name
            except KeyError as error:
                print(error)

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

            # print(appMap)

            app = ""
            friendly_name = ""
            version = 0xdeadbeef

            if task.wu_name in workUnitMap:
                # print(workUnitMap[task.wu_name])
                app = workUnitMap[task.wu_name]['app_name']
                version_str = str(workUnitMap[task.wu_name]['version_num'])
                version = '%s.%s' % (
                    version_str[0], version_str[1:])

            if app in appMap:
                friendly_name = "%s %s (%s)" % (
                    appMap[app]['user_friendly_name'], version, task.plan_class)

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
                'status': statusString
            })
        boincClient.disconnect()


def updateStatistics():
    global statsMap, projectMap

    for host, password in config['hosts'].items():
        boincClient = client.BoincClient(host=host, passwd=password)

        try:
            boincClient.connect()
        except (socket.timeout, OSError) as timeout:
            print(timeout)
            continue

        if boincClient.connected:
            statistics = boincClient.get_statistics()
            for ps in statistics.project_statistics:
                ps.project = projectMap[ps.master_url]

            statsMap[host] = statistics
            boincClient.disconnect()


def updateDiskUsage():
    global diskUsageMap, projectMap

    for host, password in config['hosts'].items():
        boincClient = client.BoincClient(host=host, passwd=password)

        try:
            boincClient.connect()
        except (socket.timeout, OSError) as timeout:
            print(timeout)
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
            boincClient.disconnect()


def updateTransfers():
    global transferMap

    for host, password in config['hosts'].items():
        boincClient = client.BoincClient(host=host, passwd=password)

        try:
            boincClient.connect()
        except (socket.timeout, OSError) as timeout:
            print(timeout)
            continue

        if boincClient.connected:
            transfers = boincClient.get_file_transfers()

            for transfer in transfers:
                transfer

            transferMap[host] = transfers
            boincClient.disconnect()