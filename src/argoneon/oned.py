#
# This script sets fan speed and monitors power button events.
#
# Fan Speed is set by sending 0 to 100 to the MCU (Micro Controller Unit).
# The values will be interpreted as the percentage of fan speed, 100% being maximum.
#
# Power button events are sent as a pulse signal to BCM Pin 4 (BOARD P7).
# A pulse width of 20-30ms indicates reboot request (double-tap).
# A pulse width of 40-50ms indicates shutdown request (hold and release after 3 secs).
#
# Additional comments are found in each function below.
#
# Standard Deployment/Triggers:
#  * Raspbian, OSMC: Runs as service via /lib/systemd/system/argononed.service
#  * lakka, libreelec: Runs as service via /storage/.config/system.d/argononed.service
#  * recalbox: Runs as service via /etc/init.d/
#

import os
import time
from os.path import join
from queue import Queue
from sys import argv, exit
from threading import Thread

import RPi.GPIO as GPIO
import smbus2 as smbus

from . import logging as log, oled, sysinfo
from .cli import Cli
from .config import (CONFIG_DIR, loadCPUFanConfig, loadDebugMode,
                     loadHDDFanConfig, loadOLEDConfig, loadTempConfig)
from .version import ARGON_VERSION

# Initialize I2C Bus
rev = GPIO.RPI_REVISION
if rev == 2 or rev == 3:
    bus = smbus.SMBus(1)
else:
    bus = smbus.SMBus(0)

CONFIG_FILE = join(CONFIG_DIR, 'eon.conf')
OLED_ENABLED = False

try:
    import datetime

    from . import oled
    OLED_ENABLED = True
except Exception as e:
    pass

#
# Enable debug logging if requested
#
log.enable(loadDebugMode())

ADDR_FAN = 0x1a
PIN_SHUTDOWN = 4

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SHUTDOWN, GPIO.IN,  pull_up_down=GPIO.PUD_DOWN)


def shutdown_check(writeq):
    """
    This function is the thread that monitors activity in our shutdown pin
    The pulse width is measured, and the corresponding shell command will be issued
    """
    while True:
        pulsetime = 1
        GPIO.wait_for_edge(PIN_SHUTDOWN, GPIO.RISING)
        time.sleep(0.01)
        while GPIO.input(PIN_SHUTDOWN) == GPIO.HIGH:
            time.sleep(0.01)
            pulsetime += 1
        if pulsetime >= 2 and pulsetime <= 3:
            # Testing
            # writeq.put("OLEDSWITCH")
            writeq.put("OLEDSTOP")
            os.system("reboot")
        elif pulsetime >= 4 and pulsetime <= 5:
            writeq.put("OLEDSTOP")
            os.system("shutdown now -h")
        elif pulsetime >= 6 and pulsetime <= 7:
            writeq.put("OLEDSWITCH")

#
#
#


def get_fanspeed(tempval: float, configlist: list[str]) -> int:
    """
    This function converts the corresponding fanspeed for the given temperature the
    configutation data is a list of strings in the form "<temperature>:<speed>"
    """
    retval = 0
    if len(configlist) > 0:
        for k in configlist.keys():
            if tempval >= float(k):
                retval = int(configlist[k])
                log.debug("Temperature (%.2f) >= (%s) suggesting fanspeed of %.1f", tempval, k, retval)
    log.debug("Returning fanspeed of %.2f", retval)
    return retval


# This function is the thread that monitors temperature and sets the fan speed
# The value is fed to get_fanspeed to get the new fan speed
# To prevent unnecessary fluctuations, lowering fan speed is delayed by 30 seconds
#
# Location of config file varies based on OS
#

def setFanOff():
    setFanSpeed(overrideSpeed=0)


def setFanFlatOut():
    setFanSpeed(overrideSpeed=100)


def setFanSpeed(overrideSpeed: int = None, instantaneous: bool = True):
    """
    Set the fanspeed.  Support override (overrideSpeed) with a specific value, and 
    an instantaneous change.  Some hardware does not like the sudden change, it wants the
    speed set to 100% THEN changed to the new value.  Not really sure why this is.
    """
    prevspeed = sysinfo.get_current_fan_speed()
    if not prevspeed:
        prevspeed = 0
        sysinfo.record_current_fan_speed(prevspeed)

    if overrideSpeed is not None:
        newspeed = overrideSpeed
    else:
        newspeed = max([get_fanspeed(sysinfo.get_cpu_temp(), loadCPUFanConfig()), get_fanspeed(sysinfo.get_max_hdd_temp(), loadHDDFanConfig())
                        ]
                       )
        if newspeed < prevspeed and not instantaneous:
            # Pause 30s before speed reduction to prevent fluctuations
            time.sleep(30)

    # Make sure the value is in 0-100 range
    newspeed = max([min([100, newspeed]), 0])
    if overrideSpeed is not None or (prevspeed != newspeed):
        try:
            if newspeed > 0:
                # Spin up to prevent issues on older units
                bus.write_byte(ADDR_FAN, 100)
                time.sleep(1)
            bus.write_byte(ADDR_FAN, int(newspeed))
            log.debug("Writing to fan port, speed %s", newspeed)
            sysinfo.record_current_fan_speed(newspeed)
        except IOError:
            log.error("Error trying to update fan speed.")
            return prevspeed
    return newspeed


def temp_check():
    """
    Main thread for processing the temperature check functonality.  We just try and set the fan speed once
    a minute.  However we do want to start with the fan *OFF*.
    """
    setFanOff()
    while True:
        setFanSpeed(instantaneous=False)
        time.sleep(60)
#
# This function is the thread that updates OLED
#


def display_loop(readq):
    weekdaynamelist = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    monthlist = ["JAN", "FEB", "MAR", "APR", "MAY",
                 "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    oledscreenwidth = oled.getmaxX()

    fontwdSml = 6    # Maps to 6x8
    fontwdReg = 8    # Maps to 8x16
    stdleftoffset = 54

    temperature = "C"
    temperature = loadTempConfig()

    print("Temperature config is " + temperature)
    screensavermode = False
    screensaversec = 120
    screensaverctr = 0

    screenenabled = ["clock", "ip"]
    prevscreen = ""
    curscreen = ""
    screenid = 0
    screenjogtime = 0
    screenjogflag = 0  # start with screenid 0
    cpuusagelist = []
    curlist = []

    tmpconfig = loadOLEDConfig()

    if "screensaver" in tmpconfig:
        screensaversec = int(tmpconfig["screensaver"])
    if "screenduration" in tmpconfig:
        screenjogtime = int(tmpconfig["screenduration"])
    if "screenlist" in tmpconfig:
        screenenabled = tmpconfig["screenlist"].replace("\"", "").split(" ")

    if "enabled" in tmpconfig:
        if tmpconfig["enabled"] == "N":
            screenenabled = []

    #
    # Setup some variables to help calculate bandwidth
    #
    timespan = 1
    prevData = sysinfo.disk_usage()
    prevTime = time.clock_gettime_ns(time.CLOCK_MONOTONIC)

    while len(screenenabled) > 0:
        if len(curlist) == 0 and screenjogflag == 1:
            # Reset Screen Saver
            screensavermode = False
            screensaverctr = 0

            # Update screen info
            screenid = screenid + screenjogflag
            if screenid >= len(screenenabled):
                screenid = 0
        prevscreen = curscreen
        curscreen = screenenabled[screenid]

        print(curscreen)
        if screenjogtime == 0:
            # Resets jogflag (if switched manually)
            screenjogflag = 0
        else:
            screenjogflag = 1

        needsUpdate = False
        if curscreen == "cpu":
            # CPU Usage
            if len(curlist) == 0:
                try:
                    if len(cpuusagelist) == 0:
                        cpuusagelist = sysinfo.list_cpu_usage()
                    curlist = cpuusagelist
                except:
                    log.error("Error processing information for CPU display")
                    curlist = []
            if len(curlist) > 0:
                oled.loadbg("bgcpu")

                # Display List
                yoffset = 0
                tmpmax = 4
                while tmpmax > 0 and len(curlist) > 0:
                    curline = ""
                    tmpitem = curlist.pop(0)
                    curline = tmpitem["title"]+": "+str(tmpitem["value"])+"%"
                    oled.writetext(curline, stdleftoffset, yoffset, fontwdSml)
                    oled.drawfilledrectangle(
                        stdleftoffset, yoffset+12, int((oledscreenwidth-stdleftoffset-4)*tmpitem["value"]/100), 2)
                    tmpmax = tmpmax - 1
                    yoffset = yoffset + 16

                needsUpdate = True
            else:
                # Next page due to error/no data
                screenjogflag = 1
        elif curscreen == "storage":
            # Storage Info
            if len(curlist) == 0:
                try:
                    tmpobj = sysinfo.list_hdd_usage()
                    for curdev in tmpobj:
                        curlist.append({"title": curdev, "value": sysinfo.kb_str(
                            tmpobj[curdev]['total']), "usage": int(tmpobj[curdev]['percent'])})
                except:
                    log.error("Error processing information for STORAGE display")
                    curlist = []
            if len(curlist) > 0:
                oled.loadbg("bgstorage")

                yoffset = 16
                tmpmax = 3
                while tmpmax > 0 and len(curlist) > 0:
                    tmpitem = curlist.pop(0)
                    # Right column first, safer to overwrite white space
                    oled.writetextaligned(
                        tmpitem["value"], 77, yoffset, oledscreenwidth-77, 2, fontwdSml)
                    oled.writetextaligned(
                        str(tmpitem["usage"])+"%", 50, yoffset, 74-50, 2, fontwdSml)
                    tmpname = tmpitem["title"]
                    if len(tmpname) > 8:
                        tmpname = tmpname[0:8]
                    oled.writetext(tmpname, 0, yoffset, fontwdSml)

                    tmpmax = tmpmax - 1
                    yoffset = yoffset + 16
                needsUpdate = True
            else:
                # Next page due to error/no data
                screenjogflag = 1

        elif curscreen == "bandwidth":
            # Bandwidth info
            if len(curlist) == 0:
                try:
                    diskdata = sysinfo.disk_usage()
                    for istop in diskdata:
                        for istart in prevData:
                            if istop['disk'] == istart['disk']:
                                istart['readsector'] = istop['readsector'] - \
                                    istart['readsector']
                                istart['writesector'] = istop['writesector'] - \
                                    istart['writesector']
                    curlist = prevData
                    prevData = diskdata
                    stoptime = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
                    timespan = (stoptime - prevTime)/1000000000
                    prevTime = stoptime
                except:
                    log.error("Error processing data for BANDWIDTH display")
                    curlist = []
            if len(curlist) > 0:

                oled.clearbuffer()
                oled.writetextaligned(
                    "BANDWIDTH", 0, 0, oledscreenwidth, 1, fontwdSml)
                oled.writetextaligned(
                    "Write", 77, 16, oledscreenwidth-77, 2, fontwdSml)
                oled.writetextaligned(
                    "Read",  50, 16, 74-50,              2, fontwdSml)
                oled.writetext("Device", 0, 16, fontwdSml)

                itemcount = 2
                yoffset = 32
                while itemcount > 0 and len(curlist) > 0:
                    item = curlist.pop(0)
                    bandwidth = int((item['writesector']/2)/timespan)
                    oled.writetextaligned(sysinfo.kb_str(
                        bandwidth), 77, yoffset, oledscreenwidth-77, 2, fontwdSml)
                    bandwidth = int((item['readsector']/2)/timespan)
                    oled.writetextaligned(sysinfo.kb_str(
                        bandwidth), 50, yoffset, 74-50, 2, fontwdSml)
                    oled.writetext(item['disk'], 0, yoffset, fontwdSml)
                    itemcount = itemcount - 1
                    yoffset = yoffset + 16

                needsUpdate = True
            else:
                # Next Page due to error/no data
                screenjogFlag = 1

        elif curscreen == "raid":
            # Raid Info
            if len(curlist) == 0:
                try:
                    tmpobj = sysinfo.list_raid()
                    curlist = tmpobj['raidlist']
                except:
                    log.error("Error processing display of RAID information.")
                    curlist = []
            if len(curlist) > 0:
                oled.loadbg("bgraid")
                tmpitem = curlist.pop(0)
                oled.writetextaligned(
                    tmpitem["title"], 0, 0, stdleftoffset, 1, fontwdSml)
                oled.writetextaligned(
                    tmpitem["value"], 0, 8, stdleftoffset, 1, fontwdSml)
                oled.writetextaligned(sysinfo.kb_str(
                    tmpitem["info"]["size"]), 0, 56, stdleftoffset, 1, fontwdSml)
                rebuild = tmpitem['info']['resync']
                statusList = tmpitem['info']['state'].split(", ")
                if len(statusList) == 1:
                    status = statusList[0]
                if len(statusList) == 2:
                    status = statusList[1]
                if len(statusList) >= 3:
                    status = statusList[2]
                status = status.capitalize()
                oled.writetext(status, stdleftoffset, 8, fontwdSml)
                if len(rebuild) > 0:
                    percent = rebuild.split(" ")
                    if status.lower() == "checking":
                        label = "Progess: "
                    else:
                        label = "Rebuild: "
                    oled.writetext(
                        label + percent[0], stdleftoffset, 16, fontwdSml)
                oled.writetext("Active:"+str(int(tmpitem["info"]["active"]))+"/"+str(
                    int(tmpitem["info"]["devices"])), stdleftoffset, 32, fontwdSml)
                oled.writetext("Working:"+str(int(tmpitem["info"]["working"]))+"/"+str(
                    int(tmpitem["info"]["devices"])), stdleftoffset, 40, fontwdSml)
                oled.writetext("Failed:"+str(int(tmpitem["info"]["failed"]))+"/"+str(
                    int(tmpitem["info"]["devices"])), stdleftoffset, 48, fontwdSml)
                needsUpdate = True
            else:
                # Next page due to error/no data
                screenjogflag = 1

        elif curscreen == "ram":
            # RAM
            try:
                oled.loadbg("bgram")
                tmpraminfo = sysinfo.get_ram()
                oled.writetextaligned(
                    tmpraminfo[0], stdleftoffset, 8, oledscreenwidth-stdleftoffset, 1, fontwdReg)
                oled.writetextaligned(
                    "of", stdleftoffset, 24, oledscreenwidth-stdleftoffset, 1, fontwdReg)
                oled.writetextaligned(
                    tmpraminfo[1], stdleftoffset, 40, oledscreenwidth-stdleftoffset, 1, fontwdReg)
                needsUpdate = True
            except:
                log.error("Error processing information for RAM display")
                needsUpdate = False
                # Next page due to error/no data
                screenjogflag = 1
        elif curscreen == "temp":
            # Temp
            try:
                oled.loadbg("bgtemp")
                hddtempctr = 0
                maxcval = 0
                mincval = 200

                # Get min/max of hdd temp
                hddtempobj = sysinfo.get_hdd_temp()
                for curdev in hddtempobj:
                    if hddtempobj[curdev] < mincval:
                        mincval = hddtempobj[curdev]
                    if hddtempobj[curdev] > maxcval:
                        maxcval = hddtempobj[curdev]
                    hddtempctr = hddtempctr + 1

                cpucval = sysinfo.get_cpu_temp()
                if hddtempctr > 0:
                    alltempobj = {"cpu": cpucval,
                                  "hdd min": mincval, "hdd max": maxcval}
                    # Update max C val to CPU Temp if necessary
                    if maxcval < cpucval:
                        maxcval = cpucval

                    displayrowht = 8
                    displayrow = 8
                    for curdev in alltempobj:
                        if temperature == "C":
                            # Celsius
                            tmpstr = str(alltempobj[curdev])
                            if len(tmpstr) > 4:
                                tmpstr = tmpstr[0:4]
                        else:
                            # Fahrenheit
                            tmpstr = str(32+9*(alltempobj[curdev])/5)
                            if len(tmpstr) > 5:
                                tmpstr = tmpstr[0:5]
                        if len(curdev) <= 3:
                            oled.writetext(curdev.upper(
                            )+": " + tmpstr + chr(167) + temperature, stdleftoffset, displayrow, fontwdSml)

                        else:
                            oled.writetext(curdev.upper()+":",
                                           stdleftoffset, displayrow, fontwdSml)

                            oled.writetext("     " + tmpstr + chr(167) + temperature,
                                           stdleftoffset, displayrow+displayrowht, fontwdSml)
                        displayrow = displayrow + displayrowht*2
                else:
                    maxcval = cpucval
                    if temperature == "C":
                        # Celsius
                        tmpstr = str(cpucval)
                        if len(tmpstr) > 4:
                            tmpstr = tmpstr[0:4]
                    else:
                        # Fahrenheit
                        tmpstr = str(32+9*(cpucval)/5)
                        if len(tmpstr) > 5:
                            tmpstr = tmpstr[0:5]

                    oled.writetextaligned(
                        tmpstr + chr(167) + temperature, stdleftoffset, 24, oledscreenwidth-stdleftoffset, 1, fontwdReg)

                # Temperature Bar: 40C is min, 80C is max
                maxht = 21
                barht = int(maxht*(maxcval-40)/40)
                if barht > maxht:
                    barht = maxht
                elif barht < 1:
                    barht = 1
                oled.drawfilledrectangle(24, 20+(maxht-barht), 3, barht, 2)

                needsUpdate = True
            except:
                log.error("Error processing temerature information for TEMP display")
                needsUpdate = False
                # Next page due to error/no data
                screenjogflag = 1
        elif curscreen == "ip":
            # IP Address
            try:
                if len(curlist) == 0:
                    curlist = sysinfo.get_ip_list()
            except:
                log.error("Error processing information for IP display")
                curlist = []

            if len(curlist) > 0:
                item = curlist.pop(0)
                oled.loadbg("bgip")
                oled.writetextaligned(
                    item[0], 0, 0, oledscreenwidth, 1, fontwdReg)
                oled.writetextaligned(
                    item[1], 0, 16, oledscreenwidth, 1, fontwdReg)
                needsUpdate = True
            else:
                needsUpdate = False
                # Next page due to error/no data
                screenjogflag = 1
        else:
            try:
                oled.loadbg("bgtime")
                # Date and Time HH:MM
                curtime = datetime.datetime.now()

                # Month/Day
                outstr = str(curtime.day).strip()
                if len(outstr) < 2:
                    outstr = " "+outstr
                outstr = monthlist[curtime.month-1]+outstr
                oled.writetextaligned(
                    outstr, stdleftoffset, 8, oledscreenwidth-stdleftoffset, 1, fontwdReg)

                # Day of Week
                oled.writetextaligned(weekdaynamelist[curtime.weekday(
                )], stdleftoffset, 24, oledscreenwidth-stdleftoffset, 1, fontwdReg)

                # Time
                outstr = str(curtime.minute).strip()
                if len(outstr) < 2:
                    outstr = "0"+outstr
                outstr = str(curtime.hour)+":"+outstr
                if len(outstr) < 5:
                    outstr = "0"+outstr
                oled.writetextaligned(
                    outstr, stdleftoffset, 40, oledscreenwidth-stdleftoffset, 1, fontwdReg)

                needsUpdate = True
            except:
                log.error("Error processing information of TIME display")
                needsUpdate = False
                # Next page due to error/no data
                screenjogflag = 1

        if needsUpdate == True:
            if screensavermode == False:
                # Update screen if not screen saver mode
                oled.power(True)
                oled.flushimage(prevscreen != curscreen)
                oled.reset()

            timeoutcounter = 0
            while timeoutcounter < screenjogtime or screenjogtime == 0:
                qdata = ""
                if readq.empty() == False:
                    qdata = readq.get()

                if qdata == "OLEDSWITCH":
                    # Trigger screen switch
                    screenjogflag = 1
                    # Reset Screen Saver
                    screensavermode = False
                    screensaverctr = 0

                    break
                elif qdata == "OLEDSTOP":
                    # End OLED Thread
                    display_defaultimg()
                    return
                else:
                    screensaverctr = screensaverctr + 1
                    if screensaversec <= screensaverctr and screensavermode == False:
                        screensavermode = True
                        oled.fill(0)
                        oled.reset()
                        oled.power(False)

                    if timeoutcounter == 0:
                        # Use 1 sec sleep get CPU usage
                        cpuusagelist = sysinfo.list_cpu_usage(1)
                    else:
                        time.sleep(1)

                    timeoutcounter = timeoutcounter + 1
                    if timeoutcounter >= 60 and screensavermode == False:
                        # Refresh data every minute, unless screensaver got triggered
                        screenjogflag = 0
                        break
    display_defaultimg()


def display_defaultimg():
    # Load default image
    # oled.power(True)
    # oled.loadbg("bgdefault")
    # oled.flushimage()
    oled.fill(0)
    oled.reset()


main = Cli('Operates the fan and billboard display on the Argon EON and Argon ONE.')


@main.command('Turn off the power.')
def cmd_shutdown():
    # Signal poweroff
    log.info("SHUTDOWN requested via shutdown of command of argononed service")
    setFanOff()
    bus.write_byte(ADDR_FAN, 0xFF)


@main.command('Turn off the fan.')
def cmd_fanoff():
    # Turn off fan
    setFanOff()
    log.info("FANOFF requested via fanoff command of the argononed service")
    if OLED_ENABLED == True:
        display_defaultimg()


@main.command('Run the a daemon that controls the fan and the ambient display.')
def cmd_service():
    # Starts the power button and temperature monitor threads
    try:
        log.info("argononed service version %s starting.", ARGON_VERSION)
        ipcq = Queue()
        t1 = Thread(target=shutdown_check, args=(ipcq, ))

        t2 = Thread(target=temp_check)
        if OLED_ENABLED == True:
            t3 = Thread(target=display_loop, args=(ipcq, ))

        t1.start()
        t2.start()
        if OLED_ENABLED == True:
            t3.start()
        ipcq.join()
    except:
        GPIO.cleanup()
