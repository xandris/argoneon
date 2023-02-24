from os.path import dirname, join

import RPi.GPIO as GPIO
import smbus2 as smbus

# Initialize I2C Bus
rev = GPIO.RPI_REVISION
if rev == 2 or rev == 3:
    bus = smbus.SMBus(1)
else:
    bus = smbus.SMBus(0)


WD = 128
HT = 64
SLAVEADDRESS = 0x6a
ADDR_OLED = 0x3c

NUMFONTCHAR = 256

BUFFERSIZE = ((WD*HT) >> 3)
imagebuffer = [0] * BUFFERSIZE


def getmaxY():
    return HT


def getmaxX():
    return WD


def loadbg(bgname):
    if bgname == "bgblack":
        clearbuffer()
        return
    elif bgname == "bgwhite":
        clearbuffer(1)
        return
    try:
        file = open(join(dirname(__file__), "oled/"+bgname+".bin"), "rb")
        bgbytes = list(file.read())
        file.close()
        ctr = len(bgbytes)
        if ctr == BUFFERSIZE:
            imagebuffer[:] = bgbytes
        elif ctr > BUFFERSIZE:
            imagebuffer[:] = bgbytes[0:BUFFERSIZE]
        else:
            imagebuffer[0:ctr] = bgbytes
            # Clear the rest of the buffer
            while ctr < BUFFERSIZE:
                imagebuffer[ctr] = 0
                ctr = ctr+1
    except FileNotFoundError:
        clearbuffer()


def clearbuffer(value=0):
    if value != 0:
        value = 0xff
    ctr = 0
    while ctr < BUFFERSIZE:
        imagebuffer[ctr] = value
        ctr = ctr+1


def writebyterow(x, y, bytevalue, mode=0):
    bufferoffset = WD*(y >> 3) + x
    if mode == 0:
        imagebuffer[bufferoffset] = bytevalue
    elif mode == 1:
        imagebuffer[bufferoffset] = bytevalue ^ imagebuffer[bufferoffset]
    else:
        imagebuffer[bufferoffset] = bytevalue | imagebuffer[bufferoffset]


def writebuffer(x, y, value, mode=0):

    yoffset = y >> 3
    yshift = y & 0x7
    ybit = (1 << yshift)

    ymask = 0xFF ^ ybit

    if value != 0:
        value = ybit

    bufferoffset = WD*yoffset + x

    curval = imagebuffer[bufferoffset]
    if mode & 1:
        imagebuffer[bufferoffset] = curval ^ value
    else:
        imagebuffer[bufferoffset] = curval & ymask | value


def fill(value):
    clearbuffer(value)
    flushimage()


def flushimage(hidescreen=True):
    if hidescreen == True:
        # Reset/Hide screen
        power(False)

    xctr = 0
    while xctr < WD:
        yctr = 0
        while yctr < HT:
            flushblock(xctr, yctr)
            yctr = yctr + 8
        xctr = xctr + 32

    if hidescreen == True:
        # Display
        power(True)


def flushblock(xoffset, yoffset):
    yoffset = yoffset >> 3
    blocksize = 32
    try:
        # Set COM-H Addressing
        bus.write_byte_data(ADDR_OLED, 0, 0x20)
        bus.write_byte_data(ADDR_OLED, 0, 0x1)

        # Set Column range
        bus.write_byte_data(ADDR_OLED, 0, 0x21)
        bus.write_byte_data(ADDR_OLED, 0, xoffset)
        bus.write_byte_data(ADDR_OLED, 0, xoffset+blocksize-1)

        # Set Row Range
        bus.write_byte_data(ADDR_OLED, 0, 0x22)
        bus.write_byte_data(ADDR_OLED, 0, yoffset)
        bus.write_byte_data(ADDR_OLED, 0, yoffset)

        # Set Display Start Line
        bus.write_byte_data(ADDR_OLED, 0, 0x40)

        bufferoffset = WD*yoffset + xoffset
        # Write Out Buffer
        bus.write_i2c_block_data(ADDR_OLED, SLAVEADDRESS,
                                 imagebuffer[bufferoffset:(bufferoffset+blocksize)])
    except:
        return


def drawfilledrectangle(x, y, wd, ht, mode=0):
    ymax = y + ht
    cury = y & 0xF8

    xmax = x + wd
    curx = x
    if ((y & 0x7)) != 0:
        yshift = y & 0x7
        bytevalue = (0xFF << yshift) & 0xFF

        # If 8 no additional masking needed
        if ymax-cury < 8:
            yshift = 8-((ymax-cury) & 0x7)
            bytevalue = bytevalue & (0xFF >> yshift)

        while curx < xmax:
            writebyterow(curx, cury, bytevalue, mode)
            curx = curx + 1
        cury = cury + 8
    # Draw 8 rows at a time when possible
    while cury + 8 < ymax:
        curx = x
        while curx < xmax:
            writebyterow(curx, cury, 0xFF, mode)
            curx = curx + 1
        cury = cury + 8

    if cury < ymax:
        yshift = 8-((ymax-cury) & 0x7)
        bytevalue = (0xFF >> yshift)

        curx = x
        while curx < xmax:
            writebyterow(curx, cury, bytevalue, mode)
            curx = curx + 1


def writetextaligned(textdata, x, y, boxwidth, alignmode, charwd=6, mode=0):
    leftoffset = 0
    if alignmode == 1:
        # Centered
        leftoffset = (boxwidth-len(textdata)*charwd) >> 1
    elif alignmode == 2:
        # Right aligned
        leftoffset = (boxwidth-len(textdata)*charwd)

    writetext(textdata, x+leftoffset, y, charwd, mode)


def writetext(textdata, x, y, charwd=6, mode=0):
    if charwd < 6:
        charwd = 6

    charht = int((charwd << 3)/6)
    if charht & 0x7:
        charht = (charht & 0xF8) + 8

    try:
        file = open(join(dirname(__file__), "oled/font" +
                    str(charht)+"x"+str(charwd)+".bin"), "rb")
        fontbytes = list(file.read())
        file.close()
    except FileNotFoundError:
        try:
            # Default to smallest
            file = open(join(dirname(__file__), "oled/font8x6.bin"), "rb")
            fontbytes = list(file.read())
            file.close()
        except FileNotFoundError:
            return

    if ((y & 0x7)) == 0:
        # Use optimized loading
        fastwritetext(textdata, x, y, charht, charwd, fontbytes, mode)
        return

    numfontrow = charht >> 3
    ctr = 0
    while ctr < len(textdata):
        fontoffset = ord(textdata[ctr])*charwd
        fontcol = 0
        while fontcol < charwd and x < WD:
            fontrow = 0
            row = y
            while fontrow < numfontrow and row < HT and x >= 0:
                curbit = 0x80
                curbyte = (fontbytes[fontoffset + fontcol +
                           (NUMFONTCHAR*charwd*fontrow)])
                subrow = 0
                while subrow < 8 and row < HT:
                    value = 0
                    if (curbyte & curbit) != 0:
                        value = 1
                    writebuffer(x, row, value, mode)
                    curbit = curbit >> 1
                    row = row + 1
                    subrow = subrow + 1
                fontrow = fontrow + 1
            fontcol = fontcol + 1
            x = x + 1
        ctr = ctr + 1


def fastwritetext(textdata, x, y, charht, charwd, fontbytes, mode=0):

    numfontrow = charht >> 3
    ctr = 0
    while ctr < len(textdata):
        fontoffset = ord(textdata[ctr])*charwd
        fontcol = 0
        while fontcol < charwd and x < WD:
            fontrow = 0
            row = y & 0xF8
            while fontrow < numfontrow and row < HT and x >= 0:
                curbyte = (fontbytes[fontoffset + fontcol +
                           (NUMFONTCHAR*charwd*fontrow)])
                writebyterow(x, row, curbyte, mode)
                fontrow = fontrow + 1
                row = row + 8
            fontcol = fontcol + 1
            x = x + 1
        ctr = ctr + 1
    return


def power(turnon=True):
    cmd = 0xAE
    if turnon == True:
        cmd = cmd | 1
    try:
        bus.write_byte_data(ADDR_OLED, 0, cmd)
    except:
        return


def inverse(enable=True):
    cmd = 0xA6
    if enable == True:
        cmd = cmd | 1
    try:
        bus.write_byte_data(ADDR_OLED, 0, cmd)
    except:
        return


def fullwhite(enable=True):
    cmd = 0xA4
    if enable == True:
        cmd = cmd | 1
    try:
        bus.write_byte_data(ADDR_OLED, 0, cmd)
    except:
        return


def reset():
    try:
        # Set COM-H Addressing
        bus.write_byte_data(ADDR_OLED, 0, 0x20)
        bus.write_byte_data(ADDR_OLED, 0, 0x1)

        # Set Column range
        bus.write_byte_data(ADDR_OLED, 0, 0x21)
        bus.write_byte_data(ADDR_OLED, 0, 0)
        bus.write_byte_data(ADDR_OLED, 0, WD-1)

        # Set Row Range
        bus.write_byte_data(ADDR_OLED, 0, 0x22)
        bus.write_byte_data(ADDR_OLED, 0, 0)
        bus.write_byte_data(ADDR_OLED, 0, (HT >> 3)-1)

        # Set Page Addressing
        bus.write_byte_data(ADDR_OLED, 0, 0x20)
        bus.write_byte_data(ADDR_OLED, 0, 0x2)
        # Set GDDRAM Address
        bus.write_byte_data(ADDR_OLED, 0, 0xB0)

        # Set Display Start Line
        bus.write_byte_data(ADDR_OLED, 0, 0x40)
    except:
        return
