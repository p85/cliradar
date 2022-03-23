import socket, sys, sqlite3, datetime, time, os, fcntl, termios, struct, math, errno
from geopy import distance
from geopy import Point
from dateutil import parser

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect(('127.0.0.1', 30003))
client_socket.setblocking(0)

log = []
data = ''
buffer = ''
timeout = str(20)
db = sqlite3.connect(':memory:')
myLat = 52.0237600
myLon = 8.5649700
R = 6371
DivMod = 10
TermReserved = 10
MaxLogItems = TermReserved - 3
VertSeparator = 100
RefreshDelay = 0.1
AntennaSym = '@ Antenna'
RadarBeamSym = '#'
UnknownSym = '?'
spinChar = '|'
spinText = 'READY'
SpeedMod = 1000
MaxMonitorEntries = 7

onDrawAngle = 0
sweepLength = 100
radiansPerFrame = 0.1

def get_line(start, end):
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    is_steep = abs(dy) > abs(dx)
    if is_steep:
        x1, y1 = y1, x1
        x2, y2 = y2, x2
    swapped = False
    if x1 > x2:
        x1, x2 = x2, x1
        y1, y2 = y2, y1
        swapped = True
    dx = x2 - x1
    dy = y2 - y1
    error = int(dx / 2.0)
    ystep = 1 if y1 < y2 else -1
    y = y1
    points = []
    for x in range(int(x1), int(x2) + 1):
        coord = (y, x) if is_steep else (x, y)
        points.append(coord)
        error -= abs(dy)
        if error < 0:
            y += ystep
            error += dx
    if swapped:
        points.reverse()
    return points

def initBeam():
    tw, th = terminal_size()
    locate(AntennaSym, tw/2, th / 2 - TermReserved)

def advanceBeam():
    global onDrawAngle
    onDrawAngle += radiansPerFrame
    tw, th = terminal_size()
    x1 = tw/2
    y1 = th/2 - TermReserved
    x2 = int(sweepLength * math.sin(onDrawAngle) + th)
    y2 = int(sweepLength * math.cos(onDrawAngle) + th)
    points = get_line([x1, y1], [x2, y2])
    for p in points:
        if p[0] < tw and p[1] < th - TermReserved and p[0] > 0 and p[1] > 0:
            locate(RadarBeamSym, p[0], p[1])

def terminal_size():
    import fcntl, termios, struct
    th, tw, hp, wp = struct.unpack('HHHH',
        fcntl.ioctl(0, termios.TIOCGWINSZ,
        struct.pack('HHHH', 0, 0, 0, 0)))
    return tw, th

def locate(user_string, x, y):
    tw, th = terminal_size()
    x = int(x)
    y = int(y)
    if x >= tw: x=tw - len(user_string)
    if y >= th: y=th
    if x <= 0: x=1
    if y <= 0: y=1
    HORIZ = str(x)
    VERT = str(y)
    sys.stdout.write("\033["+VERT+";"+HORIZ+"f"+user_string)

def init_db(cur):
    initTable = '''CREATE TABLE `data` (
    `HexID`	TEXT NOT NULL,
    `DateTime`	TEXT NOT NULL,
    `Altitude`	INTEGER NOT NULL,
    `Longitude`	REAL NOT NULL,
    `Latitude`	REAL NOT NULL,
    `LastLongitude` REAL NULL,
    `LastLatitude` REAL NULL,
    `Direction` TEXT NULL,
    `Distance`  TEXT NULL,
    `Heading`   TEXT NULL,
    `HeadingBase` TEXT NULL,
    `LastAltitude` INTEGER NULL,
    `VState`    TEXT NULL,
    `Speed`     TEXT NULL,
    `Callsign`  TEXT NULL,
    `Squawk`    TEXT NULL
    );'''
    cur.execute(initTable)
    db.commit()
    sys.stdout.write('Tables initialized\n')

def purgeOld():
    SQLQuery = 'SELECT HexID FROM data WHERE strftime(\'%s\', datetime(\'now\', \'localtime\')) - strftime(\'%s\', [DateTime]) > ' + timeout + ';'
    cur.execute(SQLQuery)
    rows = cur.fetchall()
    if cur.rowcount == -1:
        for row in rows:
            addMsg(time.strftime('%H:%M:%S') + ' Lost Track ' + str(row[0]))
        SQLQuery = 'DELETE FROM data WHERE strftime(\'%s\', datetime(\'now\', \'localtime\')) - strftime(\'%s\', [DateTime]) > ' + timeout + ';'
        cur.execute(SQLQuery)

def calcDirection(HexID, type):
    SQLQuery = 'SELECT * FROM data WHERE HexID = \'' + HexID + '\''
    cur.execute(SQLQuery)
    rows = cur.fetchone()
    if cur.rowcount != -1: return UnknownSym
    newLon = rows[3]
    newLat = rows[4]
    oldLon = rows[5]
    oldLat = rows[6]
    if newLon == None or newLat == None or oldLon == None or oldLat == None: return UnknownSym
    x1 = newLat
    y1 = newLon
    x2 = oldLat
    y2 = oldLon
    radians = math.atan2((y1 - y2), (x1 - x2))
    compassReading = radians * (180 / (4*math.atan(1)))
    if type == 1:
        coordNames = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
        coordIndex = int(round(compassReading / 45))
        if coordIndex < 0: coordIndex += 8
        return coordNames[coordIndex]
    elif type == 2:
        coordIndex = int(round(compassReading))
        if coordIndex < 0: coordIndex += 360
        return coordIndex
    elif type == 3:
        x1 = newLat
        y1 = newLon
        x2 = myLat
        y2 = myLon
        radians = math.atan2((y1 - y2), (x1 - x2))
        compassReading = radians * (180 / (4*math.atan(1)))
        coordIndex = int(round(compassReading))
        if coordIndex < 0: coordIndex += 360
        return coordIndex

def insert_db(HexID, DateTime, Altitude, Latitude, Longitude):
    tw, th = terminal_size()
    SQLQuery = 'SELECT COUNT(*) FROM data WHERE HexID = \'' + HexID + '\''
    cur.execute(SQLQuery)
    count = cur.fetchone()
    if count[0] == 0:
        SQLQuery = 'INSERT INTO data VALUES(\'' + HexID + '\', \'' + DateTime + '\', ' + Altitude + ', ' + Longitude + ', ' + Latitude + ', null, null, \'' + UnknownSym + '\', \'' + UnknownSym + '\', \'' + UnknownSym + '\', \'' + UnknownSym + '\', null, \' \', \'' + UnknownSym + '\', \'' + UnknownSym + '\', \'' + UnknownSym + '\');'
        addMsg(time.strftime('%H:%M:%S') + ' Tracking new Aircraft ' + HexID)
    else:
        direction = calcDirection(HexID, 1)
        heading = calcDirection(HexID, 2)
        headingBase = calcDirection(HexID, 3)
        distance = calculateDistance(myLon, myLat, Longitude, Latitude)
        #VState
        SQLQuery = 'SELECT Altitude, LastAltitude FROM data WHERE HexID = \'' + HexID + '\''
        cur.execute(SQLQuery)
        row = cur.fetchone()
        if row[0] == None or row[1] == None:
            VState = ' '
        else:
            if row[0] > row[1]: VState = '+'
            if row[0] < row[1]: VState = '-'
            if row[0] == row[1]: VState = ' '
        #Update
        SQLQuery = 'UPDATE data SET DateTime = \'' + str(DateTime) + '\', LastAltitude = Altitude, Altitude = ' + str(Altitude) + ', LastLongitude = Longitude, LastLatitude = Latitude, Longitude = ' + str(Longitude) + ', Latitude = ' + str(Latitude) + ', Direction = \'' + str(direction) + '\', Distance = \'' + str(distance) + '\', Heading = \'' + str(heading) + '\', HeadingBase = \'' + str(headingBase) + '\', VState = \'' + str(VState) + '\' WHERE HexID = \'' + str(HexID) + '\''
    cur.execute(SQLQuery)

def updateSpeed(HexID, spd, DateTime):
    SQLQuery = 'SELECT COUNT(*) FROM data WHERE HexID = \'' + HexID + '\''
    cur.execute(SQLQuery)
    count = cur.fetchone()
    if count[0] > 0:
        SQLQuery = 'UPDATE data SET Speed = \'' + spd + '\', DateTime = \'' + DateTime + '\' WHERE HexID = \'' + HexID + '\''
        cur.execute(SQLQuery)

def updateCs(HexID, cs, DateTime):
    SQLQuery = 'SELECT COUNT(*) FROM data WHERE HexID = \'' + HexID + '\' AND Callsign = \'?\''
    cur.execute(SQLQuery)
    count = cur.fetchone()
    if count[0] > 0:
        addMsg(time.strftime('%H:%M:%S') + ' ' + HexID + ' identified as ' + cs)
        SQLQuery = 'UPDATE data SET Callsign = \'' + cs + '\', DateTime = \'' + DateTime + '\' WHERE HexID = \'' + HexID + '\''
        cur.execute(SQLQuery)

def updateSqwk(HexID, sqwk, DateTime):
    SQLQuery = 'SELECT COUNT(*) FROM data WHERE HexID = \'' + HexID + '\''
    cur.execute(SQLQuery)
    count = cur.fetchone()
    if count[0] > 0:
        SQLQuery = 'UPDATE data SET Squawk = \'' + sqwk + '\', DateTime = \'' + DateTime + '\' WHERE HexID = \'' + HexID + '\''
        cur.execute(SQLQuery)


def dist_on_geoid(lat1, lon1, lat2, lon2):
    lat1 = lat1 * (4*math.atan(1)) / 180
    lon1 = lon1 * (4*math.atan(1)) / 90
    lat2 = lat2 * (4*math.atan(1)) / 180
    lon2 = lon2 * (4*math.atan(1)) / 90
    rho1 = R * math.cos(lat1)
    z1 = R * math.sin(lat1)
    x1 = rho1 * math.cos(lon1)
    y1 = rho1 * math.sin(lon1)
    rho2 = R * math.cos(lat2)
    z2 = R * math.sin(lat2)
    x2 = rho2 * math.cos(lon2)
    y2 = rho2 * math.sin(lon2)
    dot = (x1 * x2 + y1 * y2 + z1 * z2)
    cos_theta = dot / (R * R)
    theta = math.acos(cos_theta)
    return R * theta

def calculateDistance(startLon, startLat, endLon, endLat):
    try:
        p1 = Point(longitude=startLon, latitude=startLat)
        p2 = Point(longitude=endLon, latitude=endLat)
        dist = distance.distance(p1,p2).kilometers
        dist = str(dist)[:5]
        return dist
    except ValueError:
        return 0


def Monitor():
    SQLQuery = 'SELECT * FROM data'
    Counter = 1
    cur.execute(SQLQuery)
    rows = cur.fetchall()
    tw, th = terminal_size()
    locate('HexID   Alt      Squawk    Callsign    Distance    Direction    Heading    HeadingBase    Speed\n', 1, th - TermReserved)
    locate('================================================================================================\n', 1, th - TermReserved + 1)
    rowCounter = th - TermReserved + 2
    if cur.rowcount == -1:
        for row in rows:
            if Counter >= MaxMonitorEntries: return
            curLon = str(row[3])
            curLat = str(row[4])
            distance = calculateDistance(curLon, curLat, myLon, myLat)
            HexID = row[0]
            Alt = row[2]
            curLon = row[3]
            curLat = row[4]
            Distance = row[7]
            Direction = row[8]
            Heading = row[9]
            HeadingBase = row[10]
            VState = row[12]
            Speed = row[13]
            Callsign = row[14]
            Squawk = row[15]
            if Distance == None: Distance = UnknownSym
            if Direction == None: Direction = UnknownSym
            if Heading == None: Heading = UnknownSym
            if HeadingBase == None: HeadingBase = UnknownSym
            if Callsign == None: Callsign = UnknownSym
            if Squawk == None: Squawk = UnknownSym
            locate(str(HexID) + '   ', 1, rowCounter)
            locate(str(Alt) + '   ', 9, rowCounter)
            locate(str(VState) + '  ', 15, rowCounter)
            locate(str(Squawk) + '  ', 19, rowCounter)
            locate(str(Callsign) + '  ', 28, rowCounter)
            locate(str(Direction) + '  ', 43, rowCounter)
            locate(str(Distance)[:7] + '  ', 56, rowCounter)
            locate(str(Heading) + '  ', 67, rowCounter)
            locate(str(HeadingBase) + '  ', 81, rowCounter)
            locate(str(Speed) + '  ', 93, rowCounter)
            rowCounter += 1
            Counter += 1

def addMsg(msg):
    log.append(msg)

def paintLog():
    tw, th = terminal_size()
    counter = th - TermReserved
    lastItems = log[-MaxLogItems:]
    for item in lastItems:
        locate(item, VertSeparator + 2, counter)
        counter += 1
        if counter == th: return

def paintBorder():
    tw, th = terminal_size()
    for i in range(1,tw):
        locate('_', i, th - TermReserved - 1)
    for i in range(th - TermReserved, th):
        locate('|', VertSeparator, i)

def calcXY(hdg, dist):
    tw, th = terminal_size()
    hdg = float(hdg)
    dist = float(dist)
    x = (tw / 2) + (dist * math.sin(math.radians(hdg)))
    y = ((th - TermReserved) / 2) + (dist * math.cos(math.radians(hdg)))
    return x, y

def paintScreen():
    SQLQuery = 'SELECT * FROM data'
    cur.execute(SQLQuery)
    rows = cur.fetchall()
    tw, th = terminal_size()
    th -= TermReserved
    if cur.rowcount == -1:
        for row in rows:
            HexID = str(row[0])
            Callsign = str(row[14]).strip()
            Squawk = str(row[15])
            if Callsign == '' or Callsign == '?':
                Display = HexID
            else:
               Display = Callsign
            dist = row[8]
            hdg = row[10]
            if dist == None or dist == UnknownSym or hdg == None or hdg == UnknownSym: continue
            x, y = calcXY(hdg, dist)
            if x > tw: x = tw
            if y > th - TermReserved: y = th - TermReserved
            if x < 0: x = 1
            if y < 0: y = 1
            locate(Display, x, y)

def spinner(curChar):
    if curChar == '/': return '-'
    if curChar == '-': return '\\'
    if curChar == '\\': return '|'
    if curChar == '|': return '/'

def doSpin():
    global spinChar
    spinChar = spinner(spinChar)
    tw, th = terminal_size()
    locate(spinText + ' ' + spinChar, tw - len(spinText) - 2, th - 1)

cur = db.cursor()
init_db(cur)


while True:
    try:
        data = client_socket.recv(1024)
    except socket.error as e:
        err = e.args[0]
        if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
            data = ''
        else:
            print(e)
            sys.exit(1)
    purgeOld()
    os.system('clear')
    advanceBeam()
    initBeam()
    paintScreen()
    paintBorder()
    Monitor()
    paintLog()
    doSpin()
    buffer = data
    spl = str(buffer).split('\n')
    dti = time.strftime('%Y-%m-%d %H:%M:%S')
    for item in spl:
        splitter = item.split(',')
        #MSG Type 3 with Lon/Lat
        if len(splitter) > 15 and splitter[1] == '3' and splitter[14] != '' and splitter[15] != '':
            insert_db(splitter[4], dti, splitter[11], splitter[14], splitter[15])
        #Msg Type 4 with Speed
        elif len(splitter) > 12 and splitter[1] == '4' and splitter[12] != None:
            hexID = str(splitter[4])
            spd = str(splitter[12])
            updateSpeed(hexID, spd, dti)
        #Msg Type 5 with Callsign
        elif len(splitter) > 10 and splitter[1] == '5' and splitter[10] != None and splitter[10] != '':
            hexID = str(splitter[4])
            cs = str(splitter[10])
            updateCs(hexID, cs, dti)
        #Msg Type 6 with Squawk
        elif len(splitter) > 17 and splitter[1] == '6' and splitter[17] != None and splitter[17] != '':
            hexID = str(splitter[4])
            sqwk = str(splitter[17])
            updateSqwk(hexID, sqwk, dti)
#    else:
#        break
    time.sleep(RefreshDelay)
