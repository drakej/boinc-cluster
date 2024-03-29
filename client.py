#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# client.py - Somewhat higher-level GUI_RPC API for BOINC core client
#
#    Copyright (C) 2013 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. See <http://www.gnu.org/licenses/gpl.html>

# Based on client/boinc_cmd.cpp

import rpc
import socket
import hashlib
import datetime
import time
import logging
import configparser

from enum import IntEnum
from multiprocessing.pool import INIT
from functools import total_ordering
from xml.etree import ElementTree

LOGGER = logging.getLogger('boinc-cluster')

GUI_RPC_PASSWD_FILE = "/etc/boinc-client/gui_rpc_auth.cfg"

config = configparser.ConfigParser()

config.read('config.ini')


def setattrs_from_xml(obj, xml, attrfuncdict={}):
    ''' Helper to set values for attributes of a class instance by mapping
        matching tags from a XML file.
        attrfuncdict is a dict of functions to customize value data type of
        each attribute. It falls back to simple int/float/bool/str detection
        based on values defined in __init__(). This would not be needed if
        Boinc used standard RPC protocol, which includes data type in XML.
    '''
    if not isinstance(xml, ElementTree.Element):
        xml = ElementTree.fromstring(xml)
    for e in list(xml):
        if hasattr(obj, e.tag):
            attr = getattr(obj, e.tag)
            attrfunc = attrfuncdict.get(e.tag, None)
            if attrfunc is None:
                if isinstance(attr, bool):
                    attrfunc = parse_bool
                elif isinstance(attr, int):
                    attrfunc = parse_int
                elif isinstance(attr, float):
                    attrfunc = parse_float
                elif isinstance(attr, str):
                    attrfunc = parse_str
                elif isinstance(attr, list):
                    attrfunc = parse_list
                elif isinstance(attr, IntEnum):
                    attrfunc = parse_enum
                else:
                    def attrfunc(x, attr): return x
            setattr(obj, e.tag, attrfunc(e, attr))

    return obj


def parse_enum(e, attr):
    enum_class = type(attr)

    if e.text is None:
        return enum_class.UNKNOWN
    else:
        return enum_class(int(e.text))


def parse_bool(e, attr):
    ''' Helper to convert ElementTree.Element.text to boolean.
        Treat '<foo/>' (and '<foo>[[:blank:]]</foo>') as True
        Treat '0' and 'false' as False
    '''
    if e.text is None:
        return True
    else:
        return bool(e.text) and not e.text.strip().lower() in ('0', 'false')


def parse_int(e, attr):
    ''' Helper to convert ElementTree.Element.text to integer.
        Treat '<foo/>' (and '<foo></foo>') as 0
    '''
    # int(float()) allows casting to int a value expressed as float in XML
    return 0 if e.text is None else int(float(e.text.strip()))


def parse_float(e, attr):
    ''' Helper to convert ElementTree.Element.text to float. '''
    return 0.0 if e.text is None else float(e.text.strip())


def parse_str(e, attr):
    ''' Helper to convert ElementTree.Element.text to string. '''
    return "" if e.text is None else e.text.strip()


def parse_list(e, attr):
    ''' Helper to convert ElementTree.Element to list. For now, simply return
        the list of root element's children
    '''
    return list(e)


class NetworkStatus(IntEnum):
    ''' Values of "network_status" '''
    UNKNOWN = -1
    ONLINE = 0  # // have network connections open
    WANT_CONNECTION = 1  # // need a physical connection
    WANT_DISCONNECT = 2  # // don't have any connections, and don't need any
    LOOKUP_PENDING = 3  # // a website lookup is pending (try again later)

    @classmethod
    def name(cls, v):
        name_hash = {
            cls.UNKNOWN: "unknown",
            cls.ONLINE: "online",
            cls.WANT_CONNECTION: "need connection",
            cls.WANT_DISCONNECT: "don't need connection",
            cls.LOOKUP_PENDING: "reference site lookup pending"
        }

        if v in name_hash:
            return name_hash[v]
        else:
            return "unknown"


class RPCReason(IntEnum):
    ''' beep boop

    '''
    UNKNOWN = -1
    USER_REQ = 1
    RESULTS_DUE = 2
    NEED_WORK = 3
    TRICKLE_UP = 4
    ACCT_MGR_REQ = 5
    INIT = 6
    PROJECT_REQ = 7

    @classmethod
    def name(cls, v):
        name_hash = {
            cls.UNKNOWN: "unkown",
            cls.USER_REQ: "Requested by user",
            cls.RESULTS_DUE: "To report completed tasks",
            cls.NEED_WORK: "To fetch work",
            cls.TRICKLE_UP: "To send trickle-up message",
            cls.ACCT_MGR_REQ: "Requested by account manager",
            cls.INIT: "Project initialization",
            cls.PROJECT_REQ: "Requested by project"
        }

        if v in name_hash:
            return name_hash[v]
        else:
            return "unknown"


class SuspendReason(IntEnum):
    ''' bitmap defs for task_suspend_reason, network_suspend_reason
        Note: doesn't need to be a bitmap, but keep for compatibility
    '''
    UNKNOWN = -1
    NOT_SUSPENDED = 0  # Not in original API
    BATTERIES = 1
    USER_ACTIVE = 2
    USER_REQ = 4
    TIME_OF_DAY = 8
    BENCHMARKS = 16
    DISK_SIZE = 32
    CPU_THROTTLE = 64
    NO_RECENT_INPUT = 128
    INITIAL_DELAY = 256
    EXCLUSIVE_APP_RUNNING = 512
    CPU_USAGE = 1024
    NETWORK_QUOTA_EXCEEDED = 2048
    OS = 4096
    WIFI_STATE = 4097
    BATTERY_CHARGING = 4098
    BATTERY_OVERHEATED = 4099

    @classmethod
    def name(cls, v):
        name_hash = {
            cls.UNKNOWN: "unknown reason",
            cls.NOT_SUSPENDED: "not suspended",
            cls.BATTERIES: "on batteries",
            cls.USER_ACTIVE: "computer is in use",
            cls.USER_REQ: "user request",
            cls.TIME_OF_DAY: "time of day",
            cls.BENCHMARKS: "CPU benchmarks in progress",
            cls.DISK_SIZE: "need disk space - check preferences",
            cls.NO_RECENT_INPUT: "no recent user activity",
            cls.INITIAL_DELAY: "initial delay",
            cls.EXCLUSIVE_APP_RUNNING: "an exclusive app is running",
            cls.CPU_USAGE: "CPU is busy",
            cls.NETWORK_QUOTA_EXCEEDED: "network bandwidth limit exceeded",
            cls.OS: "requested by operating system",
            cls.WIFI_STATE: "not connected to WiFi network",
            cls.BATTERY_CHARGING: "battery is charging",
            cls.BATTERY_OVERHEATED: "battery is overheated"
        }

        if v in name_hash:
            return name_hash[v]
        else:
            return "unknown"


class RunMode(IntEnum):
    ''' Run modes for CPU, GPU, network,
        controlled by Activity menu and snooze button
    '''
    UNKNOWN = -1
    ALWAYS = 1
    AUTO = 2
    NEVER = 3
    RESTORE = 4
    # // restore permanent mode - used only in set_X_mode() GUI RPC

    @classmethod
    def name(cls, v):
        # all other modes use the fallback name
        if v == cls.AUTO:
            return "according to prefs"
        else:
            return cls[v].name()


def mode_name(mode):
    modes = {
        1: 'always',
        2: 'auto',
        3: 'never',
        4: 'restore'
    }

    name = "unknown"

    LOGGER.debug(f"mode: {mode}")

    if mode in modes:
        name = modes[mode]

    return name


class CpuSched(IntEnum):
    ''' values of ACTIVE_TASK::scheduler_state and ACTIVE_TASK::next_scheduler_state
        "SCHEDULED" is synonymous with "executing" except when CPU throttling
        is in use.
    '''
    UNKNOWN = -1
    UNINITIALIZED = 0
    PREEMPTED = 1
    SCHEDULED = 2


class ResultState(IntEnum):
    ''' Values of RESULT::state in client.
        THESE MUST BE IN NUMERICAL ORDER
        (because of the > comparison in RESULT::computing_done())
        see html/inc/common_defs.inc
    '''
    UNKNOWN = -1
    NEW = 0
    # // New result
    FILES_DOWNLOADING = 1
    # // Input files for result (WU, app version) are being downloaded
    FILES_DOWNLOADED = 2
    # // Files are downloaded, result can be (or is being) computed
    COMPUTE_ERROR = 3
    # // computation failed; no file upload
    FILES_UPLOADING = 4
    # // Output files for result are being uploaded
    FILES_UPLOADED = 5
    # // Files are uploaded, notify scheduling server at some point
    ABORTED = 6
    # // result was aborted
    UPLOAD_FAILED = 7
    # // some output file permanent failure


class Process(IntEnum):
    ''' values of ACTIVE_TASK::task_state '''
    UNINITIALIZED = 0
    # // process doesn't exist yet
    EXECUTING = 1
    # // process is running, as far as we know
    SUSPENDED = 9
    # // we've sent it a "suspend" message
    ABORT_PENDING = 5
    # // process exceeded limits; send "abort" message, waiting to exit
    QUIT_PENDING = 8
    # // we've sent it a "quit" message, waiting to exit
    COPY_PENDING = 10
    # // waiting for async file copies to finish


class _Struct(object):
    ''' base helper class with common methods for all classes derived from
        BOINC's C++ structs
    '''
    @classmethod
    def parse(cls, xml):
        return setattrs_from_xml(cls(), xml)

    def __str__(self, indent=0):
        buf = '%s%s:\n' % ('\t' * indent, self.__class__.__name__)
        for attr in self.__dict__:
            value = getattr(self, attr)
            if isinstance(value, list):
                buf += '%s\t%s [\n' % ('\t' * indent, attr)
                for v in value:
                    buf += '\t\t%s\t\t,\n' % v
                buf += '\t]\n'
            else:
                buf += '%s\t%s\t%s\n' % ('\t' * indent,
                                         attr,
                                         value.__str__(indent+2)
                                         if isinstance(value, _Struct)
                                         else repr(value))
        return buf


@total_ordering
class VersionInfo(_Struct):
    def __init__(self):
        self.major = 0
        self.minor = 0
        self.release = 0
        self.prerelease = False

    @property
    def _tuple(self):
        return (self.major, self.minor, self.release)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self._tuple == other._tuple

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._tuple > other._tuple

    def __str__(self):
        return "%d.%d.%d" % (self.major, self.minor, self.release)

    def __repr__(self):
        return "%s%r" % (self.__class__.__name__, self._tuple)


class CCStatus(_Struct):
    def __init__(self):
        self.network_status = NetworkStatus.UNKNOWN
        self.ams_password_error = False
        self.manager_must_quit = False

        self.task_suspend_reason = SuspendReason.UNKNOWN  # // bitmap
        self.task_mode = RunMode.UNKNOWN
        self.task_mode_perm = RunMode.UNKNOWN  # // same, but permanent version
        self.task_mode_delay = 0.0  # // time until perm becomes actual

        self.network_suspend_reason = SuspendReason.UNKNOWN
        self.network_mode = RunMode.UNKNOWN
        self.network_mode_perm = RunMode.UNKNOWN
        self.network_mode_delay = 0.0

        self.gpu_suspend_reason = SuspendReason.UNKNOWN
        self.gpu_mode = RunMode.UNKNOWN
        self.gpu_mode_perm = RunMode.UNKNOWN
        self.gpu_mode_delay = 0.0

        self.disallow_attach = False
        self.simple_gui_only = False

        self.max_event_log_lines = 0


class HostInfo(_Struct):
    def __init__(self):
        self.timezone = 0  # // local STANDARD time - UTC time (in seconds)
        self.domain_name = ""
        self.ip_addr = ""
        self.host_cpid = ""

        self.p_ncpus = 0  # // Number of CPUs on host
        self.p_vendor = ""  # // Vendor name of CPU
        self.p_model = ""  # // Model of CPU
        self.p_features = ""
        self.p_fpops = 0.0  # // measured floating point ops/sec of CPU
        self.p_iops = 0.0  # // measured integer ops/sec of CPU
        self.p_membw = 0.0  # // measured memory bandwidth (bytes/sec) of CPU
        # // The above are per CPU, not total
        self.p_calculated = 0.0  # // when benchmarks were last run, or zero
        self.p_vm_extensions_disabled = False

        self.m_nbytes = 0  # // Size of memory in bytes
        self.m_cache = 0  # // Size of CPU cache in bytes (L1 or L2?)
        self.m_swap = 0  # // Size of swap space in bytes

        self.d_total = 0  # // Total disk space on volume containing
        # // the BOINC client directory.
        self.d_free = 0  # // how much is free on that volume

        self.os_name = ""  # // Name of operating system
        self.os_version = ""  # // Version of operating system

        # // the following is non-empty if VBox is installed
        self.virtualbox_version = ""

        self.product_name = ""
        self.wsl_available = False

        self.coprocs = []  # COPROCS

        self.n_usable_coprocs = 0

        # The following are currently unused (not in RPC XML)
        self.serialnum = ""  # // textual description of coprocessors

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        hostinfo = super(HostInfo, cls).parse(xml)

        # parse each coproc in coprocs list
        aux = []
        for c in hostinfo.coprocs:
            aux.append(Coproc.parse(c))
        hostinfo.coprocs = aux

        return hostinfo


class Coproc(_Struct):
    ''' represents a set of identical coprocessors on a particular computer.
        Abstract class;
        objects will always be a derived class (COPROC_CUDA, COPROC_ATI)
        Used in both client and server.
    '''

    def __init__(self):
        self.type = ""  # // must be unique
        self.count = 0  # // how many are present
        self.peak_flops = 0.0
        self.used = 0.0  # // how many are in use (used by client)
        self.have_cuda = False  # // True if this GPU supports CUDA on this computer
        self.have_cal = False  # // True if this GPU supports CAL on this computer
        self.have_opencl = False  # // True if this GPU supports openCL on this computer
        self.available_ram = 0
        self.specified_in_config = False
        # // If true, this coproc was listed in cc_config.xml
        # // rather than being detected by the client.

        # // the following are used in both client and server for work-fetch info
        self.req_secs = 0.0
        # // how many instance-seconds of work requested
        self.req_instances = 0.0
        # // client is requesting enough jobs to use this many instances
        self.estimated_delay = 0
        # // resource will be saturated for this long

        self.opencl_device_count = 0
        self.last_print_time = 0.0

        self.cudaVersion = None
        self.drvVersion = None
        self.totalGlobalMem = None
        self.sharedMemPerBlock = None
        self.regsPerBlock = None
        self.warpSize = None
        self.memPitch = None
        self.maxThreadsPerBlock = None
        self.maxThreadsDim = None
        self.maxGridSize = None
        self.clockRate = None
        self.totalConstMem = None

        self.coproc_opencl = None

        self.version = None
        self.name = ""

        self.textureAlignment = None
        self.deviceOverlap = None
        self.multiProcessorCount = None
        self.pci_info = None

        self.major = None
        self.minor = None
        # self.opencl_prop = None  # OPENCL_DEVICE_PROP

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        coprocs = super(Coproc, cls).parse(xml)

        # parse each coproc in coprocs list
        coprocs.coproc_opencl = CoprocOpenCL.parse(coprocs.coproc_opencl)

        return coprocs


class CoprocOpenCL(_Struct):
    def __init__(self):
        self.name = ""

        self.vendor = ""
        self.vendor_id = ""
        self.available = False

        self.single_fp_config = None
        self.double_fp_config = None

        self.endian_little = False
        self.execution_capabilities = None
        self.extensions = None

        self.global_mem_size = 0
        self.local_mem_size = 0
        self.max_clock_frequency = 0.0
        self.max_compute_units = 0

        self.nv_compute_capability_major = None
        self.nv_compute_capability_minor = None

        self.amd_simd_per_compute_unit = None
        self.amd_simd_width = None
        self.amd_simd_instruction_width = None

        self.opencl_platform_version = ""
        self.opencl_device_version = ""
        self.opencl_driver_version = ""

        self.half_fp_config = None


class ProjectListEntry(_Struct):
    def __init__(self):
        self.name = ""
        self.url = ""
        self.web_url = ""
        self.general_area = ""
        self.specific_area = ""
        self.description = ""
        self.home = ""
        self.image = ""
        self.platforms = []


class Project(_Struct):
    def __init__(self):
        self.master_url = ""
        self.project_name = ""
        self.symstore = None
        self.user_name = ""
        self.team_name = ""
        self.host_venue = None
        self.email_hash = ""
        self.cross_project_id = ""
        self.external_cpid = ""
        self.cpid_time = 0.0

        self.user_total_credit = 0.0
        self.user_expavg_credit = 0.0
        self.user_create_time = 0.0

        self.rpc_seqno = 0

        self.userid = 0
        self.teamid = 0
        self.hostid = 0

        self.host_total_credit = 0.0
        self.host_expavg_credit = 0.0
        self.host_create_time = 0.0

        self.min_rpc_time = 0.0
        self.next_rpc_time = 0.0

        self.nrpc_failures = None
        self.master_fetch_failures = None

        self.rec = 0.0

        self.rec_time = 0.0
        self.resource_share = 0.0
        self.desired_disk_usage = 0.0

        self.duration_correction_factor = 0.0

        self.sched_rpc_pending = 0
        self.send_time_stats_log = 0
        self.send_job_log = 0

        self.njobs_success = 0
        self.njobs_error = 0

        self.elapsed_time = 0.0
        self.last_rpc_time = 0.0
        self.dont_use_dcf = None

        self.rsc_backoff_time = None
        self.rsc_backoff_interval = None

        self.dont_request_more_work = False

        self.verify_files_on_app_start = None

        self.gui_urls = []

        self.sched_priority = 0.0
        self.project_files_downloaded_time = 0.0
        self.project_dir = ""

        self.non_cpu_intensive = False
        self.suspended_via_gui = False

        self.scheduler_rpc_in_progress = False
        self.trickle_up_pending = False

        self.ended = False
        self.detach_when_done = False

        self.venue = None

        self.disk_usage = None
        self.disk_share = None
        self.no_rsc_apps = None

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        result = super(Project, cls).parse(xml)

        return result

    def __str__(self):
        buf = '%s:\n' % self.__class__.__name__
        for attr in self.__dict__:
            value = getattr(self, attr)
            if attr in ['rec_time', 'user_create_time', 'host_create_time']:
                value = time.ctime(value)
            buf += '\t%s\t%r\n' % (attr, value)
        return buf


class Statistics(_Struct):
    ''' Wraps up the project specific statistics '''

    def __init__(self):
        self.project_statistics = []

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        statistics = super(Statistics, cls).parse(xml)

        aux = []
        for element in list(xml):
            aux.append(ProjectStatistics.parse(element))
        statistics.project_statistics = aux

        return statistics


class ProjectStatistics(_Struct):
    def __init__(self):
        self.daily_statistics = []
        self.master_url = ""

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        projectStatistics = super(ProjectStatistics, cls).parse(xml)

        aux = []
        for element in list(xml):
            if element.tag == 'daily_statistics':
                aux.append(DailyStatistics.parse(element))
        projectStatistics.daily_statistics = aux

        return projectStatistics


class DailyStatistics(_Struct):
    def __init__(self):
        self.day = None
        self.day_timestamp = 0
        self.user_total_credit = 0.0
        self.user_expavg_credit = 0.0
        self.host_total_credit = 0.0
        self.host_expavg_credit = 0.0

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        dailyStatistics = super(DailyStatistics, cls).parse(xml)
        children = list(xml)

        for child in children:
            if child.tag == 'day':
                dailyStatistics.day = datetime.datetime.fromtimestamp(
                    float(child.text))
                dailyStatistics.day_timestamp = int(float(child.text))

        return dailyStatistics


class DiskUsageSummary(_Struct):
    def __init__(self):
        self.projects = []

        self.d_total = 0
        self.d_free = 0
        self.d_boinc = 0
        self.d_allowed = 0

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        diskUsageSummary = super(DiskUsageSummary, cls).parse(xml)
        children = list(xml)

        for child in children:
            if child.tag == 'project':
                diskUsageSummary.projects.append(DiskUsageProject.parse(child))

        return diskUsageSummary


class DiskUsageProject(_Struct):
    def __init__(self):
        self.master_url = ""
        self.disk_usage = 0


class FileTransfer(_Struct):
    def __init__(self):
        self.project_url = ""
        self.project_name = ""
        self.name = ""
        self.nbytes = 0.0
        self.max_nbytes = 0.0
        self.status = 0
        self.bytes_xferred = 0.0
        self.file_offset = 0.0
        self.xfer_speed = 0.0
        self.hostname = ""
        self.project_backoff = 0.0
        self.project = None
        self.persistent_file_xfer = None

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        file_transfer = super(FileTransfer, cls).parse(xml)

        persistent_file_xfer = PersistentFileXFer.parse(
            file_transfer.persistent_file_xfer)

        file_transfer.num_retries = persistent_file_xfer.num_retries
        file_transfer.first_request_time = persistent_file_xfer.first_request_time
        file_transfer.next_request_time = persistent_file_xfer.next_request_time
        file_transfer.time_so_far = persistent_file_xfer.time_so_far
        file_transfer.last_bytes_xferred = persistent_file_xfer.last_bytes_xferred
        file_transfer.is_upload = persistent_file_xfer.is_upload

        return file_transfer


class PersistentFileXFer(_Struct):
    def __init__(self):
        self.num_retries = 0
        self.first_request_time = 0.0
        self.next_request_time = 0.0
        self.time_so_far = 0.0
        self.last_bytes_xferred = 0.0
        self.is_upload = False


class OldResult(_Struct):
    def __init__(self):
        self.project_url = ""
        self.result_name = ""
        self.app_name = ""

        self.exit_status = 0
        self.elapsed_time = 0.0
        self.cpu_time = 0.0
        self.completed_time = 0.0
        self.create_time = 0.0


class Result(_Struct):
    ''' Also called "task" in some contexts '''

    def __init__(self):
        # Names and values follow lib/gui_rpc_client.h @ RESULT
        # Order too, except when grouping contradicts client/result.cpp
        # RESULT::write_gui(), then XML order is used.

        self.name = ""
        self.wu_name = ""
        self.version_num = 0
        # // identifies the app used
        self.plan_class = ""
        self.project_url = ""  # from PROJECT.master_url
        self.report_deadline = 0.0  # seconds since epoch
        self.received_time = 0.0  # seconds since epoch
        # // when we got this from server
        self.ready_to_report = False
        # // we're ready to report this result to the server;
        # // either computation is done and all the files have been uploaded
        # // or there was an error
        self.got_server_ack = False
        # // we've received the ack for this result from the server
        self.final_cpu_time = 0.0
        self.final_elapsed_time = 0.0
        self.state = ResultState.NEW
        self.estimated_cpu_time_remaining = 0.0
        # // actually, estimated elapsed time remaining
        self.exit_status = 0
        # // return value from the application
        self.suspended_via_gui = False
        self.project_suspended_via_gui = False
        self.edf_scheduled = False
        # // temporary used to tell GUI that this result is deadline-scheduled
        self.coproc_missing = False
        # // a coproc needed by this job is missing
        # // (e.g. because user removed their GPU board).
        self.scheduler_wait = False
        self.scheduler_wait_reason = ""
        self.network_wait = False
        self.resources = ""
        # // textual description of resources used

        # // the following defined if active
        # XML is generated in client/app.cpp ACTIVE_TASK::write_gui()
        self.active_task = False
        self.active_task_state = Process.UNINITIALIZED
        self.app_version_num = 0
        self.slot = -1
        self.pid = 0
        self.scheduler_state = CpuSched.UNINITIALIZED
        self.checkpoint_cpu_time = 0.0
        self.current_cpu_time = 0.0
        self.fraction_done = 0.0
        self.elapsed_time = 0.0
        self.swap_size = 0
        self.working_set_size_smoothed = 0.0
        self.too_large = False
        self.needs_shmem = False
        self.graphics_exec_path = ""
        self.web_graphics_url = ""
        self.remote_desktop_addr = ""
        self.slot_path = ""
        # // only present if graphics_exec_path is

        # The following are not in original API, but are present in RPC XML reply
        self.completed_time = 0.0
        # // time when ready_to_report was set
        self.report_immediately = False
        self.working_set_size = 0
        self.page_fault_rate = 0.0
        # // derived by higher-level code

        # The following are in API, but are NEVER in RPC XML reply. Go figure
        self.signal = 0

        self.app = None  # APP*
        self.wup = None  # WORKUNIT*
        self.project = None  # PROJECT*
        self.avp = None  # APP_VERSION*

        self.progress_rate = None
        self.platform = None
        self.bytes_sent = None
        self.bytes_received = None

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        # parse main XML
        result = super(Result, cls).parse(xml)

        # parse '<active_task>' children
        active_task = xml.find('active_task')
        if active_task is None:
            result.active_task = False  # already the default after __init__()
        else:
            result.active_task = True   # already the default after main parse
            result = setattrs_from_xml(result, active_task)

        # // if CPU time is nonzero but elapsed time is zero,
        # // we must be talking to an old client.
        # // Set elapsed = CPU
        # // (easier to deal with this here than in the manager)
        if result.current_cpu_time != 0 and result.elapsed_time == 0:
            result.elapsed_time = result.current_cpu_time

        if result.final_cpu_time != 0 and result.final_elapsed_time == 0:
            result.final_elapsed_time = result.final_cpu_time

        return result

    def __str__(self):
        buf = '%s:\n' % self.__class__.__name__
        for attr in self.__dict__:
            value = getattr(self, attr)
            if attr in ['received_time', 'report_deadline']:
                value = time.ctime(value)
            buf += '\t%s\t%r\n' % (attr, value)
        return buf


class WorkUnit(_Struct):
    def __init__(self) -> None:

        self.name = ""
        self.app_name = ""
        self.version_num = 0

        self.rsc_memory_bound = 0.0
        self.rsc_fpops_est = 0.0
        self.rsc_fpops_bound = 0.0
        self.rsc_disk_bound = 0.0
        self.command_line = ""

        self.file_refs = []

        @classmethod
        def parse(cls, xml):
            if not isinstance(xml, ElementTree.Element):
                xml = ElementTree.fromstring(xml)

            workUnit = super(WorkUnit, cls).parse(xml)
            children = list(xml)

            for child in children:
                if child.tag == 'file_ref':
                    workUnit.file_refs.append(FileRef.parse(child))

            return workUnit


class App(_Struct):
    def __init__(self):

        self.name = ""
        self.user_friendly_name = ""
        self.non_cpu_intensive = 0


class FileRef(_Struct):
    def __init__(self):

        self.file_name = ""
        self.main_program = False
        self.open_name = ""


class ProejctAttachReply(_Struct):
    error_num = 0
    messages = []


class AppVersion(_Struct):
    def __init__(self):

        self.app_name = ""
        self.version_num = 0
        self.platform = ""
        self.avg_ncpus = 0.0
        self.flops = 0.0
        self.plan_class = ""
        self.api_version = ""
        self.file_refs = []

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        appVersion = super(AppVersion, cls).parse(xml)
        children = list(xml)

        for child in children:
            if child.tag == 'file_ref':
                appVersion.file_refs.append(FileRef.parse(child))

        return appVersion


class CCState(_Struct):
    def __init__(self):

        self.host_info = None
        self.have_cuda = False
        self.have_ati = False

        self.projects = []

        self.apps = []
        self.app_versions = []

        self.results = []

        self.work_units = []

        platforms = []

    @classmethod
    def parse(cls, xml):
        if not isinstance(xml, ElementTree.Element):
            xml = ElementTree.fromstring(xml)

        clientState = super(CCState, cls).parse(xml)
        children = list(xml)

        for child in children:
            if child.tag == 'host_info':
                clientState.host_info = HostInfo.parse(child)

            if child.tag == 'project':
                clientState.projects.append(Project.parse(child))

            if child.tag == 'result':
                clientState.results.append(Result.parse(child))

            if child.tag == 'app':
                clientState.apps.append(App.parse(child))

            if child.tag == 'app_version':
                clientState.app_versions.append(AppVersion.parse(child))

            if child.tag == 'workunit':
                clientState.work_units.append(WorkUnit.parse(child))

        return clientState


class BoincClient(object):

    def __init__(self, host="", passwd=None):
        host = host.split(':', 1)

        self.hostname = host[0]
        self.port = int(host[1]) if len(host) == 2 else 31416
        self.passwd = passwd
        self.rpc = rpc.Rpc(text_output=False)
        self.version = None
        self.authorized = False

        if 'version' in config['application']:
            self.version = config['application']['version']

        # Informative, not authoritative. Records status of *last* RPC call,
        # but does not infer success about the *next* one.
        # Thus, it should be read *after* an RPC call, not prior to one
        self.connected = False

    def __enter__(self): self.connect(); return self
    def __exit__(self, *args): self.disconnect()

    def connect(self):
        try:
            self.rpc.connect(self.hostname, self.port)
            self.connected = True
        except socket.error:
            self.connected = False

            LOGGER.error(
                f"Socket error, {self.hostname} client connectioned failed")
            return
        self.authorized = self.authorize(self.passwd)
        self.version = self.exchange_versions(f'BOINC Cluster {self.version}')

    def disconnect(self):
        LOGGER.debug(f"{self.hostname} client disconnected...")
        self.rpc.disconnect()

    def authorize(self, password):
        ''' Request authorization. If password is None and we are connecting
            to localhost, try to read password from the local config file
            GUI_RPC_PASSWD_FILE. If file can't be read (not found or no
            permission to read), try to authorize with a blank password.
            If authorization is requested and fails, all subsequent calls
            will be refused with socket.error 'Connection reset by peer' (104).
            Since most local calls do no require authorization, do not attempt
            it if you're not sure about the password.
        '''

        if password is None and not self.hostname:
            password = read_gui_rpc_password() or ""

        nonce = self.rpc.call('<auth1/>').text
        inputStr = '%s%s' % (nonce, password)
        hash = hashlib.md5(inputStr.encode('utf-8')).hexdigest().lower()
        reply = self.rpc.call(
            '<auth2><nonce_hash>%s</nonce_hash></auth2>' % hash)

        if reply.tag == 'authorized':
            return True
        else:
            return False

    def exchange_versions(self, name):
        ''' Return VersionInfo instance with core client version info '''
        version_parts = self.version.split('.')
        LOGGER.debug(f'version_parts: {version_parts}')
        return VersionInfo.parse(self.rpc.call("<exchange_versions>\n"
                                               f"   <major>{version_parts[0]}</major>\n"
                                               f"   <minor>{version_parts[1]}</minor>\n"
                                               f"   <release>{version_parts[2]}</release>\n"
                                               "   <name>{name}</name>\n"
                                               "</exchange_versions>\n"))

    def get_state(self):
        return CCState.parse(self.rpc.call('<get_state/>'))

    def get_results(self, active_only=False):
        ''' Get a list of results.
            Those that are in progress will have information such as CPU time
            and fraction done. Each result includes a name;
            Use CC_STATE::lookup_result() to find this result in the current static state;
            if it's not there, call get_state() again.
        '''
        reply = self.rpc.call("<get_results><active_only>%d</active_only></get_results>"
                              % (1 if active_only else 0))
        if not reply.tag == 'results':
            return []

        results = []
        for item in list(reply):
            results.append(Result.parse(item))

        return results

    def get_old_results(self):
        reply = self.rpc.call("<get_old_results/>")

        if not reply.tag == "old_results":
            return []

        old_results = []

        for item in list(reply):
            old_results.append(OldResult.parse(item))

        return old_results

    def get_file_transfers(self):
        transfers_xml = self.rpc.call("<get_file_transfers/>")

        LOGGER.debug(f"Transfers XML: {transfers_xml}")

        if not transfers_xml.tag == 'file_transfers':
            return []

        transfers = []

        for transfer in list(transfers_xml):
            transfers.append(FileTransfer.parse(transfer))

        return transfers

    def get_simple_gui_info(self):
        reply = self.rpc.call("<get_simple_gui_info/>")

        projects = []
        results = []

        for item in list(reply):
            if item.tag == "project":
                projects.append(Project.parse(item))
            elif item.tag == "result":
                results.append(Result.parse(item))

        return (projects, results)

    def get_project_status(self):
        reply = self.rpc.call("<get_project_status/>")

        if not reply or not reply.tag == 'projects':
            return []

        projects = []
        for item in list(reply):
            projects.append(Project.parse(item))

        return projects

    def get_all_project_list(self):
        reply = self.rpc.call("<get_all_projects_list/>")

        if not reply or not reply.tag == 'projects':
            return []

        projects = []
        for item in list(reply):
            projects.append(ProjectListEntry.parse(item))

        return projects

    def get_disk_usage(self):
        return DiskUsageSummary.parse(self.rpc.call('<get_disk_usage/>'))

    def get_statistics(self):
        return Statistics.parse(self.rpc.call('<get_statistics/>'))

    def get_cc_status(self):
        ''' Return CCStatus instance containing basic status, such as
            CPU / GPU / Network active/suspended, etc
        '''
        if not self.connected:
            LOGGER.info(
                f"Not connected, {self.hostname} client connection attempt...")
            self.connect()
        try:
            return CCStatus.parse(self.rpc.call('<get_cc_status/>'))
        except socket.error as error:
            self.connected = False

            LOGGER.error(
                f"Socket error, {self.hostname} client connectioned failed")

    def network_available(self):
        return self.rpc.call("<network_available/>")

    def project_op(self, project, op=""):
        if op == "reset":
            tag = "project_reset"
        elif op == "detach":
            tag = "project_detach"
        elif op == "update":
            tag == "project_update"
        elif op == "suspend":
            tag == "project_suspend"
            project.suspended_via_gui = True
        elif op == "resume":
            tag == "project_resume"
            project.suspended_via_gui = False
        elif op == "allowmorework":
            tag = "project_allowmorework"
            project.dont_request_more_work = False
        elif op == "nomorework":
            tag = "project_nomorework"
            project.dont_request_more_work = True
        elif op == "detach_when_done":
            tag = "project_detach_when_done"
        elif op == "dont_detach_when_done":
            tag = "project_dont_detach_when_done"
        else:
            return -1

        reply = self.rpc.call(
            f"<{tag}><project_url>{project.master_url}</project_url></{tag}>")

        return reply

    def project_attach_from_file(self):
        return self.rpc.call("<project_attach>\n"
                             "  <use_config_file/>\n"
                             "</project_attach>\n")

    def project_attach(self, url, authenticator, name):
        return self.rpc.call("<project_attach>\n"
                             f"<project_url>{url}</project_url>"
                             f"<authenticator>{authenticator}</authenticator>"
                             f"<project_name>name</project_name>")

    def project_attach_poll(self):
        reply = self.rpc.call("<project_attach_poll/>")

        if not reply or reply.tag != "project_attach_reply":
            return None

        return ProejctAttachReply.parse(reply)

    def set_mode(self, component, mode, duration=0):
        ''' Do the real work of set_{run,gpu,network}_mode()
            This method is not part of the original API.
            Valid components are 'run' (or 'cpu'), 'gpu', 'network' (or 'net')
        '''
        component = component.replace('cpu', 'run')
        component = component.replace('net', 'network')
        try:
            reply = self.rpc.call(f"<set_{component}_mode>"
                                  f"<{mode_name(mode)}/><duration>{duration}</duration>"
                                  f"</set_{component}_mode>")

            LOGGER.debug(f"<set_{component}_mode>"
                         f"<{mode_name(mode)}/><duration>{duration}</duration>"
                         f"</set_{component}_mode>")
            return (reply.tag == 'success')
        except socket.error:
            return False

    def set_run_mode(self, mode, duration=0):
        ''' Set the run mode (RunMode.NEVER/AUTO/ALWAYS/RESTORE)
            NEVER will suspend all activity, including CPU, GPU and Network
            AUTO will run according to preferences.
            If duration is zero, mode is permanent. Otherwise revert to last
            permanent mode after duration seconds elapse.
        '''
        return self.set_mode('cpu', mode, duration)

    def set_gpu_mode(self, mode, duration=0):
        ''' Set the GPU run mode, similar to set_run_mode() but for GPU only
        '''
        return self.set_mode('gpu', mode, duration)

    def set_network_mode(self, mode, duration=0):
        ''' Set the Network run mode, similar to set_run_mode()
            but for network activity only
        '''
        return self.set_mode('net', mode, duration)

    def run_benchmarks(self):
        ''' Run benchmarks. Computing will suspend during benchmarks '''
        return self.rpc.call('<run_benchmarks/>').tag == "success"

    def get_screensaver_tasks(self):
        ''' Get Screensaver Tasks.'''
        reply = self.rpc.call("<get_screensaver_tasks/>")

        if not reply or not reply.tag == "get_screensaver_tasks":
            return []

        tasks = []

        for task in list(reply):
            tasks.append(Result.parse(task))

        return tasks

    def get_host_info(self):
        ''' Get information about host hardware and usage. '''
        return HostInfo.parse(self.rpc.call('<get_host_info/>'))

    def get_tasks(self):
        ''' Same as get_results(active_only=False) '''
        return self.get_results(False)

    def add_account(self, url="", email="", password=""):
        '''
        '''
        password_hash = hashlib.md5(email.encode(
            'utf-8')+password.encode('utf-8')).hexdigest().lower()

        reply = self.rpc.call("<create_account>\n"
                              f"<url>{url}</url>\n"
                              f"<email_addr>{email}</email_addr>\n"
                              f"<passwd_hash>{password_hash}</passwd_hash>\n"
                              f"<user_name></user_name>\n"
                              f"<team_name></team_name>\n"
                              "<consented_to_terms/>\n"
                              "</create_account>\n")

        LOGGER.debug(
            f"create_account response for host {self.hostname}: {reply}")

        return reply

    def quit(self):
        ''' Tell the core client to exit '''
        if self.rpc.call('<quit/>').tag == "success":
            self.connected = False
            return True
        return False


def read_gui_rpc_password():
    ''' Read password string from GUI_RPC_PASSWD_FILE file, trim the last CR
        (if any), and return it
    '''
    try:
        with open(GUI_RPC_PASSWD_FILE, 'r') as f:
            buf = f.read()
            if buf.endswith('\n'):
                return buf[:-1]  # trim last CR
            else:
                return buf
    except IOError:
        # Permission denied or File not found.
        pass
