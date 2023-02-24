#!/bin/bash

echo "*************"
echo " Argon Setup  "
echo "*************"

# Helper variables
ARGONDOWNLOADSERVER=https://raw.githubusercontent.com/JeffCurless/argoneon/main/
INSTALLATIONFOLDER=/etc/argon

versioninfoscript=$INSTALLATIONFOLDER/argon-versioninfo.sh

uninstallscript=$INSTALLATIONFOLDER/argon-uninstall.sh
shutdownscript=/lib/systemd/system-shutdown/argon-shutdown.sh
statusscript=$INSTALLATIONFOLDER/argon-status.py
statuscmd=argon-status
configscript=$INSTALLATIONFOLDER/argon-config
unitconfigscript=$INSTALLATIONFOLDER/argon-unitconfig.sh

setupmode="Setup"

if [ -f $configscript ]
then
    setupmode="Update"
    echo "Updating files"
else
    sudo mkdir $INSTALLATIONFOLDER
    sudo chmod 755 $INSTALLATIONFOLDER
fi


argon_check_pkg() {
    RESULT=$(dpkg-query -W -f='${Status}\n' "$1" 2> /dev/null | grep "installed")

    if [ "" == "$RESULT" ]; then
        echo "NG"
    else
        echo "OK"
    fi
}

CHECKPLATFORM="Others"
pretty_name=`grep PRETTY_NAME /etc/os-release | awk -F"=" '{print $2}' | sed 's/"//g'`
echo ${pretty_name} | grep -q -F Ubuntu
if [ $? -eq 0 ]
then
    version=`echo ${pretty_name} | awk '{print $2}' | awk -F"." '{print $1"."$2}'`
    echo ${version}
    if [ "${version}" == "21.04" ]
    then
        echo "Installing on Ubuntu 21.04"
        pkglist=(raspi-gpio python3-rpi.gpio python3-smbus i2c-tools curl smartmontools)
    elif [ "${version}" == "21.10" ]
    then
        echo "Installing on Ubuntu 21.10"
        pkglist=(python3-lgpio python3-rpi.gpio python3-smbus i2c-tools python3-psutil curl smartmontools)
    elif [ "${version}" == "22.04" ]
    then
        echo "Installing on Ubuntu version 22.04"
        pkglist=(python3-lgpio python3-rpi.gpio python3-smbus i2c-tools python3-psutil curl smartmontools)
    else
        echo "Unsupported Ubuntu verison: " ${pretty_name}
	exit
    fi
else
    echo ${pretty_name} | grep -q -F -e 'Raspbian' -e 'bullseye' /etc/os-release &> /dev/null
    if [ $? -eq 0 ]
    then
        echo "Installing on RaspberryPI OS"
        pkglist=(raspi-gpio python3-rpi.gpio python3-smbus i2c-tools python3-psutil curl smartmontools)
        CHECKPLATFORM="Raspbian"
    fi
fi

for curpkg in ${pkglist[@]}; do
    sudo apt-get install -y $curpkg
    RESULT=$(argon_check_pkg "$curpkg")
    if [ "NG" == "$RESULT" ]
    then
        echo "********************************************************************"
        echo "Please also connect device to the internet and restart installation."
        echo "********************************************************************"
        exit
    fi
done

# Ubuntu Mate for RPi has raspi-config too
command -v raspi-config &> /dev/null
if [ $? -eq 0 ]
then
    # Enable i2c and serial
    sudo raspi-config nonint do_i2c 0
    sudo raspi-config nonint do_serial 2
fi

# Fan Setup
basename="argonone"
daemonname=$basename"d"
irconfigscript=$INSTALLATIONFOLDER/${basename}-ir.sh
powerbuttonscript=$INSTALLATIONFOLDER/$daemonname.py
argoneonconfig=$INSTALLATIONFOLDER/argoneon.conf
daemonconfigfile=/etc/$daemonname.conf
daemonfanservice=/lib/systemd/system/$daemonname.service

# Fan Daemon/Service Files
sudo curl -L $ARGONDOWNLOADSERVER/argononed.py -o $powerbuttonscript --silent
sudo chmod 644 $powerbuttonscript
sudo curl -L $ARGONDOWNLOADSERVER/argononed.service -o $daemonfanservice --silent
sudo chmod 644 $daemonfanservice

# IR Files
sudo curl -L $ARGONDOWNLOADSERVER/argonone-ir.sh -o $irconfigscript --silent
sudo chmod 755 $irconfigscript

# Other utility scripts
sudo curl -L $ARGONDOWNLOADSERVER/argon-versioninfo.sh -o $versioninfoscript --silent
sudo chmod 755 $versioninfoscript

sudo curl -L $ARGONDOWNLOADSERVER/argonsysinfo.py -o $INSTALLATIONFOLDER/argonsysinfo.py --silent
sudo chmod 755 $INSTALLATIONFOLDER/argonsysinfo.py
sudo curl -L $ARGONDOWNLOADSERVER/argonconfig.py -o $INSTALLATIONFOLDER/argonconfig.py --silent
sudo chmod 755 $INSTALLATIONFOLDER/argonconfig.py
sudo curl -L $ARGONDOWNLOADSERVER/argonlogging.py -o $INSTALLATIONFOLDER/argonlogging.py --silent
sudo chmod 755 $INSTALLATIONFOLDER/argonlogging.py
sudo curl -L $ARGONDOWNLOADSERVER/version.py -o $INSTALLATIONFOLDER/version.py --silent
sudo chmod 755 $INSTALLATIONFOLDER/version.py

# RTC Setup
basename="argoneon"
daemonname=$basename"d"

rtcconfigfile=/etc/argoneonrtc.conf
rtcconfigscript=$INSTALLATIONFOLDER/${basename}-rtcconfig.sh
daemonrtcservice=/lib/systemd/system/$daemonname.service
rtcdaemonscript=$INSTALLATIONFOLDER/$daemonname.py

oledlibscript=$INSTALLATIONFOLDER/${basename}oled.py
oledconfigfile=/etc/argoneonoled.conf

# Generate default RTC config file if non-existent
if [ ! -f $rtcconfigfile ]; then
    sudo touch $rtcconfigfile
    sudo chmod 666 $rtcconfigfile

    echo '#' >> $rtcconfigfile
    echo '# Argon RTC Configuration' >> $rtcconfigfile
    echo '#' >> $rtcconfigfile
fi

# RTC Config Script
sudo curl -L $ARGONDOWNLOADSERVER/argoneon-rtcconfig.sh -o $rtcconfigscript --silent
sudo chmod 755 $rtcconfigscript

# RTC Daemon/Service Files
sudo curl -L $ARGONDOWNLOADSERVER/argoneond.py -o $rtcdaemonscript --silent
sudo chmod 644 $rtcdaemonscript 
sudo curl -L $ARGONDOWNLOADSERVER/argoneond.service -o $daemonrtcservice --silent
sudo chmod 644 $daemonrtcservice
sudo curl -L $ARGONDOWNLOADSERVER/argoneonoled.py -o $oledlibscript --silent
sudo chmod 755 $oledlibscript

if [ ! -d $INSTALLATIONFOLDER/oled ]
then
    sudo mkdir $INSTALLATIONFOLDER/oled
fi

for binfile in font8x6 font16x12 font32x24 font64x48 font16x8 font24x16 font48x32 bgdefault bgram bgip bgtemp bgcpu bgraid bgstorage bgtime
do
    sudo curl -L $ARGONDOWNLOADSERVER/oled/${binfile}.bin -o $INSTALLATIONFOLDER/oled/${binfile}.bin --silent 
done



# Argon Uninstall Script
sudo  curl -L $ARGONDOWNLOADSERVER/argon-uninstall.sh -o $uninstallscript --silent
sudo chmod 755 $uninstallscript

# Argon Shutdown script
sudo curl -L $ARGONDOWNLOADSERVER/argon-shutdown.sh -o $shutdownscript --silent
sudo chmod 755 $shutdownscript

# Argon Status script
sudo curl -L $ARGONDOWNLOADSERVER/argon-status.py -o $statusscript --silent
sudo chmod 755 $statusscript
if [ -f /usr/bin/$statuscmd ]
then
    sudo rm /usr/bin/$statuscmd
fi
sudo ln -s $statusscript /usr/bin/$statuscmd

# Argon Config Script
if [ -f $configscript ]; then
    sudo rm $configscript
fi
sudo touch $configscript

# To ensure we can write the following lines
sudo chmod 666 $configscript

#!/bin/bash' >> $configscript

echo "--------------------------"
echo "Argon Configuration Tool"
$versioninfoscript simple
echo "--------------------------"

get_number () {
    read curnumber
    if [ -z "$curnumber" ]
    then
        echo "-2"
        return
    elif [[ $curnumber =~ ^[+-]?[0-9]+$ ]]
    then
        if [ $curnumber -lt 0 ]
        then
            echo "-1"
            return
        elif [ $curnumber -gt 100 ]
        then
            echo "-1"
            return
        fi    
        echo $curnumber
        return
    fi
    echo "-1"
    return
}


mainloopflag=1
while [ $mainloopflag -eq 1 ]
do
    echo
    echo "Choose Option:"
    echo "  1. Configure IR"
    echo "  2. Configure RTC and/or Schedule"
    echo "  3. Uninstall"
    echo ""
    echo "  0. Exit"
    echo -n "Enter Number (0-3):"
    newmode=$( get_number )


    if [ $newmode -eq 0 ]
    then
        echo "Thank you."
        mainloopflag=0

    elif [ $newmode -eq 1 ]
    then
        $irconfigscript
        mainloopflag=0

    elif [ $newmode -eq 2 ]
    then
        $rtcconfigscript
        mainloopflag=0

    elif [ $newmode -eq 3 ]
    then
        $uninstallscript
        mainloopflag=0
    fi
done

sudo chmod 755 $configscript

# Desktop Icon
currentuser=`whoami`
shortcutfile="/home/${currentuser}/Desktop/argonone-config.desktop"
if [ "$CHECKPLATFORM" = "Raspbian" ] && [ -d "/home/${currentuser}/Desktop" ]
then
    terminalcmd="lxterminal --working-directory=/home/pi/ -t"
    if  [ -f "/home/pi/.twisteros.twid" ]
    then
        terminalcmd="xfce4-terminal --default-working-directory=/home/pi/ -T"
    fi
    imagefile=argoneon.png
    sudo curl -L $ARGONDOWNLOADSERVER/$imagefile -o /usr/share/pixmaps/$imagefile --silent
    if [ -f $shortcutfile ]; then
        sudo rm $shortcutfile
    fi

    # Create Shortcuts
    echo "[Desktop Entry]" > $shortcutfile
    echo "Name=Argon Configuration" >> $shortcutfile
    echo "Comment=Argon Configuration" >> $shortcutfile
    echo "Icon=/usr/share/pixmaps/$imagefile" >> $shortcutfile
    echo 'Exec='$terminalcmd' "Argon Configuration" -e '$configscript >> $shortcutfile
    echo "Type=Application" >> $shortcutfile
    echo "Encoding=UTF-8" >> $shortcutfile
    echo "Terminal=false" >> $shortcutfile
    echo "Categories=None;" >> $shortcutfile
    chmod 755 $shortcutfile
fi

configcmd="$(basename -- $configscript)"

if [ "$setupmode" = "Setup" ]
then
    if [ -f "/usr/bin/$configcmd" ]
    then
        sudo rm /usr/bin/$configcmd
    fi
    sudo ln -s $configscript /usr/bin/$configcmd

    sudo ln -s $configscript /usr/bin/argonone-config
    sudo ln -s $uninstallscript /usr/bin/argonone-uninstall
    sudo ln -s $irconfigscript /usr/bin/argonone-ir


    # Enable and Start Service(s)
    sudo systemctl daemon-reload
    sudo systemctl enable argononed.service
    sudo systemctl start argononed.service
    sudo systemctl enable argoneond.service
    sudo systemctl start argoneond.service
else
    sudo systemctl daemon-reload
    sudo systemctl restart argononed.service
    sudo systemctl restart argoneond.service
fi

echo "*********************"
echo "  $setupmode Completed "
echo "*********************"
$versioninfoscript
echo 
echo "Use '$configcmd' to configure device"
echo
