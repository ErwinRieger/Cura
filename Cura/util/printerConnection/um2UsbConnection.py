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
# from Cura.util import machineCom
from Cura.util.printerConnection.printerConnectionBase import printerConnectionBase
from Cura.util.printerConnection.ultiprint import Preprocessor

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

class Um2UsbConnection(printerConnectionBase):
	"""
	A serial connection. Needs to build an active-connection.
	When an active connection is created, a 2nd python process is spawned which handles the actual serial communication.

	This class communicates with the Cura.serialCommunication module trough stdin/stdout pipes.
	"""
	def __init__(self, port):

		printerConnectionBase.__init__(self, "UM2 at " + port)

		self._portName = port

		baud = profile.getMachineSetting('serial_baud')

		# XXX AUTO is not allowed yet
		assert(baud != "AUTO")

		self._baudrate = int(baud)

		self._temperature = []
		self._targetTemperature = []
		self._bedTemperature = 0
		self._targetBedTemperature = 0
		self._log = []

		self._commStateString = ""
		self.gcodeData = []
		self.gcodePos = 0

		# Flag, print or store gcode
		self.storeMode = False
		self._serial = None
		self.wantReply = None
		self.wantAck = None
		# Part of a response read from printer
		self.recvPart = ""

		self.endStoreToken = "Done saving"
		self.endTokens = ['echo:enqueing "M84"']   

		self.printing = False
		self.startTime = None

		self.dataStream = None

		# Timespan where we monitor the serial line after the
		# print has finished.
		self.postMonitor = 0

	def showMessage(self, s):
		print s
		self._commStateString = s
		self._doCallback()

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
			self._serial = serial.Serial(self._portName, self._baudrate, timeout=0.05, writeTimeout=1)
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

	def setStoreMode(self, storeMode):
		self.storeMode = storeMode

		if storeMode:
			self.endTokens = [self.endStoreToken, 'echo:enqueing "M84"']
		else:
			self.endTokens = ['echo:enqueing "M84"']   

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

		mode = "print"
		if self.storeMode:
			mode = "store"

		self.dataStream.seekStart();
		prep = Preprocessor(mode, stream = self.dataStream)

		prep.printStat()

		self.gcodeData = prep.prep
		self.gcodePos = 0

		self.printing = True

		self.startTime = time.time()

		self._printProgress = 0

		if self.storeMode:
			self.showMessage("Start store.")
		else:
			self.showMessage("Start print.")


	#Abort the previously loaded print file
	def cancelPrint(self):

		self.printing = False

		self.postMonitor = time.time() + 10

		if self.wantAck:
			print "Clearing stale wantAck..."
			self.wantAck = False

		if self.wantReply:
			print "Clearing stale wantReply..."
			self.wantReply = None

		if self.storeMode:

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
		if len(self.gcodeData) < 1:
			return 0.0
		return float(self._printProgress) / float(len(self.gcodeData))

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

		if self.printing:
			print "XXX stop printing here..."
			assert(0)

		if self._serial:
			self._serial.close()
			self._serial = None

	#Is the active connection open right now.
	def isActiveConnectionOpen(self):
		return True

	#Are we trying to open an active connection right now.
	def isActiveConnectionOpening(self):
		return False

	def getTemperature(self, extruder):
		return 245.6;
		if extruder >= len(self._temperature):
			return None
		return self._temperature[extruder]

	def getBedTemperature(self):
		return 123.4;
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

		if not self.printing and time.time() > self.postMonitor:
			return

		if time.time() <  self.postMonitor: 
			print "postmon: ", self.wantAck, self.wantReply, self.gcodePos
		
		if self.printing:
			print "print: ", self.wantAck, self.wantReply, self.gcodePos

		if self.printing and not self.wantAck and not self.wantReply and self.gcodePos < len(self.gcodeData):
			# send a line
			(line, self.wantReply) = self.gcodeData[self.gcodePos]
			self.send(line)
			self.gcodePos += 1
			self.lastSend = time.time()
			self.wantAck = True

			# We have sent a command to the printer, request more
			# cpu cycles from wx to process the answer quickly
			ev.RequestMore(True)

		recvLine = self.saveReadline()		  

		if not recvLine:
			return

		# There was something to read, so request more
		# cpu cycles from wx
		ev.RequestMore(True)

		if self.recvPart:
			recvLine = self.recvPart + recvLine
			self.recvPart = None

		if recvLine[-1] != "\n":
			self.recvPart = recvLine
			return

		if self.checkError(recvLine):
			# command resend
			self.wantAck = False
			self.wantReply = None
			return

		if self.wantAck and recvLine[0] == chr(0x6):
			print "ACK"
			self.wantAck = False
			return

		if self.wantReply and recvLine.startswith(self.wantReply):
			print "Got Required reply: ", recvLine,
			self.wantReply = None
		else:
			print "Reply: ", recvLine,

		if recvLine.startswith(self.endStoreToken):

			print "\n-----------------------------------------------"
			print "Store statistics:"
			print "-----------------------------------------------\n"
			duration = time.time() - self.startTime
			print "Sent %d commands in %.1f seconds, %.1f commands/second.\n" % (len(self.gcodeData), duration, len(self.gcodeData)/duration)

		for token in self.endTokens:
			if recvLine.startswith(token):

				# self.readMore()
				self.postMonitor = time.time() + 5

				print "end-reply received, print/store done ..."
				self.printing = False
				self.showMessage("Print/Store finished.")
				return

	# Read a response from printer, "handle" exceptions
	def saveReadline(self):

		result = ""

		while True:
			try:
				c = self._serial.read()
				# print "c: ", c
			except serial.SerialException as ex:
				print "saveReadline() Exception raised:", ex
				break

			if not c:
				break

			result += c

			if c == "\n":
				break

			if ord(c) == 0x6:
				result += "\n"
				break

		return result

	# Monitor printer responses for a while (wait waitcount * 0.1 seconds)
	def readMore(self, waitcount=100):

		print "waiting %.2f seconds for more messages..." % (waitcount/20.0)

		for i in range(waitcount):

			recvLine = self.saveReadline()		  

			if recvLine:
				if ord(recvLine[0]) > 20:
					print "Reply: ", recvLine,
				else:
					print "Reply: 0x%s" % recvLine.encode("hex")


	# Send a command to the printer, add a newline if 
	# needed.
	def send(self, cmd):

		if isPackedCommand(cmd):
		
			print "\nSend: ", cmd.encode("hex")
			self._serial.write(cmd)
		else:

			print "\nSend: ", cmd,
			self._serial.write(cmd)

	# Check a printer response for an error
	def checkError(self, recvLine):

		if "Error:" in recvLine and	 "Last Line" in recvLine:
			# Error:Line Number is not Last Line Number+1, Last Line: 9			   
			# Error:checksum mismatch, Last Line: 71388
			lastLine = int(recvLine.split(":")[2])

			print "\nERROR:"
			print "Reply: ", recvLine,
			print "Scheduling resend of command...", lastLine+1

			# assert(self.gcodePos == lastLine + 2)

			self.gcodePos = lastLine + 1

			# Slow down a bit in case of error
			time.sleep(0.1)
			return True

		for token in ["Error:", "cold extrusion", "SD init fail", "open failed"]:
			if token in recvLine:

				self.printing = False

				s = "ERROR: reply from printer: '%s'" % recvLine
				self.showError(s)

				self.reset()

	# Stop and reset the printer
	# xxx does not work right yet, um2 display still says 'preheating...'
	def reset(self):

		print "\nResetting printer"

		# send("M29\n") # End sd write, response: "Done saving"
		# send("G28\n") # Home all Axis, response: ok
		# send("M84\n") # Disable steppers until next move, response: ok
		# send("M104 S0\n") # Set temp
		# send("M140 S0\n") # Set temp

		gcode = ["M29", "G28", "M84", "M104 S0", "M140 S0"]
		prep = Preprocessor("reset", gcode = map(lambda x: (x, None), gcode))

		print "Reset code sequence: ", prep.prep

		for (cmd, resp) in prep.prep:
			self.send(cmd)
			self.readMore(20)


