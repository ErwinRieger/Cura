"""
Cura 'printer driver' for ultimaker2 over usbserial (Ultimaker2Marlin-USBPrint firmware).
"""

__copyright__ = """
Based on serialConnection.py,
	Copyright (C) 2013 David Braam - Released under terms of the AGPLv3 License
Copyright (C) 2014 Erwin Rieger: heavy modifications for UM2 USB print.
"""

import time

import serial
import ultiprint

from Cura.util import profile
from Cura.util.printerConnection.printerConnectionBase import printerConnectionBase
from Cura.util.printerConnection.ultiprint import Preprocessor, Printer
from Cura.util.printerConnection.serialConnection import serialConnectionGroup

def isPackedCommand(cmd):
	return cmd[0] < "\n"

class Um2UsbConnectionGroup(serialConnectionGroup):
	"""
	The serial connection group. Keeps track of all available serial ports,
	and builds a Um2UsbConnection for each port.
	"""
	def __init__(self):
		serialConnectionGroup.__init__(self, "UM2USB") 

	def createSerialConnection(self, port):
		return Um2UsbConnection(port)

	def getPriority(self):
		"""
		XXX uses the same value as serialConnectionGroup, the two connection types are
		used alternately.
		"""
		return 50

	def ultiGCodeCapable(self):
		"""
		Returns True if this printer understands the UltiGCode flavour.
		"""
		return True


class Um2UsbConnection(printerConnectionBase, Printer):
	"""
	A serial connection. Needs to build an active-connection.
	This class acts as a Connector between cura and the ultiprint.py Printer
	class.
	"""
	def __init__(self, port):

		printerConnectionBase.__init__(self, "UM2 at " + port)
		Printer.__init__(self)

		baud = profile.getMachineSetting('serial_baud')

		# XXX AUTO is not allowed yet
		assert(baud != "AUTO")

		self._portName = port
		self._baudrate = int(baud)

		self._temperature = []
		self._targetTemperature = []
		self._bedTemperature = 0
		self._targetBedTemperature = 0
		self._log = []

		self._commStateString = ""

		self.dataStream = None

	def showMessage(self, s):
		print "showMessage: %s" % s
		self._commStateString = s
		# Pass string also to _doCallback, to skip "rate limiting" in 
		# doPrinterConnectionUpdate()
		self._doCallback(s)

	def showError(self, s):

		self._log.append(s)
		self.showMessage(s)

	#Load the data into memory for printing, returns True on success
	def loadGCodeData(self, dataStream):

		print "Um2UsbConnection.py::loadGCodeData", dataStream

		if self.isPrinting():
			return False

		self._log = []

		self.showMessage("Open serial port.")

		print "open serial: ", self._portName, self._baudrate
		try:
			self.initSerial(self._portName, br=self._baudrate)
		except serial.SerialException as ex:
			s = "Can't open serial port %s with baudrate %d: '%s'" % (self._portName, self._baudrate, str(ex))
			print s
			self.showError(s)
			return False

		print "Um2UsbConnection.py::loadGCodeData, #codes:", len(dataStream)

		self.dataStream = dataStream

		self.wantReply = "echo:SD card ok"

		self.showMessage("Serial port opened.")
		return True

	def hasStoreMode(self):
		return True

	# Flag, print or store gcode
	def setStoreMode(self, storeMode):

		if storeMode:
			self.initMode("store")
		else:
			self.initMode("print")

	def hasOnIdle(self):
		"""
		Return True if this driver uses/needs onIdle gui events.
		"""
		return True


	#Start printing the previously loaded file
	def startPrint(self):

		if self.isPrinting() or len(self.dataStream) < 1:
			return

		self.showMessage("Preprocessing gcode.")

		self.dataStream.seekStart();
		prep = Preprocessor(self.mode, stream = self.dataStream)

		prep.printStat()

		self.gcodeData = prep.prep
		self.gcodePos = 0

		self.printing = True

		self.startTime = time.time()

		self._printProgress = 0

		self.showMessage("Start %s." % self.mode)

	#Abort the previously loaded print file
	def cancelPrint(self, immediate=False):

		self.printing = False

		if not immediate:
			self.postMonitor = time.time() + 10

		if self.wantAck:
			print "Clearing stale wantAck..."
			self.wantAck = False

		if self.wantReply:
			print "Clearing stale wantReply..."
			self.wantReply = None

		if self.mode == "store":

			self.showMessage("Close sd file.")

			prep = Preprocessor("reset", gcode = [("M29", None)])

			for (cmd, resp) in prep.prep:
				self.send(cmd)
				self.readMore(20)
		else:
			self.showMessage("Resetting printer.")
			self.reset()

		self.showMessage("Stopped.")

	def isPrinting(self):
		return self.printing

	#Amount of progression of the current print file. 0.0 to 1.0
	def getPrintProgress(self):

		if not len(self.gcodeData):
			return 0.0

		return float(self.gcodePos) / len(self.gcodeData)

	# Return if the printer with this connection type is available
	def isAvailable(self):
		return True

	# Get the connection status string. This is displayed to the user and can be used to
	# communicate various information to the user.
	def getStatusString(self):
		return self._commStateString

	#Returns true if we need to establish an active connection. True for serial connections.
	def hasActiveConnection(self):
		print "hasActiveConnection"
		return True

	#Close the active connection to the printer
	def closeActiveConnection(self):

		print "closeActiveConnection"

		self.postMonitor = 0

		if self.printing:
			self.cancelPrint(True)

		self.close()

	#Is the active connection open right now.
	def isActiveConnectionOpen(self):
		return True

	#Are we trying to open an active connection right now.
	def isActiveConnectionOpening(self):
		return False

	def getTemperature(self, extruder):
		return 0;
		if extruder >= len(self._temperature):
			return None
		return self._temperature[extruder]

	def getBedTemperature(self):
		return 0;
		return self._bedTemperature

	#Returns true if we got some kind of error. The getErrorLog returns all the information to diagnose the problem.
	def isInErrorState(self):
		return self._log != []

	#Returns the error log in case there was an error.
	def getErrorLog(self):
		return '\n'.join(self._log)

	def _serialCommunicationThread(self):

		assert(0);

		if platform.system() == "Darwin" and hasattr(sys, 'frozen'):
			cmdList = [os.path.join(os.path.dirname(sys.executable), 'Cura'), '--serialCommunication']
			cmdList += [self._portName + ':' + profile.getMachineSetting('serial_baud')]
		else:
			cmdList = [sys.executable, '-m', 'Cura.serialCommunication']
			cmdList += [self._portName, profile.getMachineSetting('serial_baud')]
		if platform.system() == "Darwin":
			if platform.machine() == 'i386':
				cmdList = ['arch', '-i386'] + cmdList
		self._process = subprocess.Popen(cmdList, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
		line = self._process.stdout.readline()
		while len(line) > 0:
			line = line.strip()
			line = line.split(':', 1)
			if line[0] == '':
				pass
			elif line[0] == 'log':
				self._log.append(line[1])
				if len(self._log) > 30:
					self._log.pop(0)
			elif line[0] == 'temp':
				line = line[1].split(':')
				self._temperature = json.loads(line[0])
				self._targetTemperature = json.loads(line[1])
				self._bedTemperature = float(line[2])
				self._targetBedTemperature = float(line[3])
				self._doCallback()
			elif line[0] == 'message':
				self._doCallback(line[1])
			elif line[0] == 'state':
				line = line[1].split(':', 1)
				self._commState = int(line[0])
				self._commStateString = line[1]
				self._doCallback()
			elif line[0] == 'progress':
				self._printProgress = int(line[1])
				self._doCallback()
			else:
				print line
			line = self._process.stdout.readline()
		self._process = None


	def onIdle(self, ev):
		"""
		Called if gui is idle, to perform 'background tasks'
		"""

		self.processCommand(ev)


















