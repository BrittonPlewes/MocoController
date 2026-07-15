import os, sys, time

if sys.platform == "win32":
    sys.path.insert( 0, "E:/Projects/Moco/python/lib")

from pathlib import Path
from PyQt5 import QtCore
from SerialManager import SerialManager



def utf8len(s):
    return len(s.encode('utf-8'))



class GcodeJobWorker(QtCore.QObject):
    """Sends a gcode file line-by-line using the SerialManager.

    Emits progress signals and lines that go to the serial monitor.
    """
    progress = QtCore.pyqtSignal(int, int)  # sent_lines, total_lines
    finished_ok = QtCore.pyqtSignal()
    finished_error = QtCore.pyqtSignal(str)
    sent_line = QtCore.pyqtSignal(str)  # emitted when we write a line

    setPaused = QtCore.pyqtSignal(bool) ## this is a mess
    runLoop = QtCore.pyqtSignal()

    def __init__(self, serial_manager: SerialManager, parent=None,
                 line_delay=0.0, ack_timeout=5.0):
        super().__init__(parent)
        self.serial = serial_manager
        self.gcode = []
        self._stop = False
        self.line_delay = line_delay
        self.ack_timeout = ack_timeout

        self._running = False
        self._pause = False

        self.total = 0
        self.sent = 0
        self.bufferSpace = [0,0]

        self.connectSignals()

    def connectSignals(self):
        self.setPaused.connect(self.updatePaused)
        self.runLoop.connect(self.loop)

    @QtCore.pyqtSlot(list)    
    def setBuffer( self, data ):
        self.bufferSpace = data

        if self._running and self.pause:
            if len(self.gcode[self.line]) < self.bufferSpace[1]:
                print( "buffer has space! unpausing" )
                self.setPaused.emit(False)
        

    @QtCore.pyqtSlot(list)
    def updateGcode( self, gcode ):
        self.gcode = gcode
        self.total = len(self.gcode)
        #print( "gcode lines: ", self.total )        


    def prep(self):
        print( "starting!" )
        
        #self.sent = 0
        self.line = 0
        self.pause = False
        self._stop = False
        self._running = True
        #self.start()

    

    @QtCore.pyqtSlot(bool)
    def updatePaused( self, tog ):
        self._pause = tog

        if self._running and not self._pause:
            self.runLoop.emit()

    @QtCore.pyqtSlot()
    def loop(self):
        if self._running:
            if not self._pause:
                ## check planner space
                if self.bufferSpace[0] <= 0:
                    print("no planner space left, pausing")                    
                    self.setPaused.emit(True)
                    return
                
                print( self.line )
                print( "next line: ", self.gcode[self.line], " -> ", len(self.gcode[self.line]) )

                ## check Rx buffer
                if self.bufferSpace[1] - len(self.gcode[self.line]) <=0:
                    print("no rx buffer space left, pausing")                    
                    self.setPaused.emit(True)
                    return

                ## maybe we're at the end of the gcode??
                if self.line >= self.total:
                    ## run through all the 
                    self.finished_ok.emit()                                    
                    self._running = False
                    print("sent all the lines!")
                    return                
                else:
                    self.sendLine(self.line)                    
                    self.bufferSpace[0] -= 1
                    self.bufferSpace[1] -= len(self.gcode[self.line])
                    #print("sending ", self.line, self.bufferSpace)                    
                    self.line += 1

                    if self.line_delay:
                        time.sleep(self.line_delay)
                    self.runLoop.emit()
                    





       
    def sendLine( self, line ):
        text = self.gcode[line]

  
        # strip comments and blanks according to simple rules
        text = text.strip()
        if not text or text.startswith('(') or text.startswith(';'):
            # still send blank lines? usually not
            #sent += 1
            self.progress.emit(line, self.total)
            return
            #continue
        # send and wait for ack
        ok, resp = self.serial.send_and_wait_ack(text, timeout=self.ack_timeout)
        # emit what we sent so monitor shows it
        self.sent_line.emit(f"> {text}")
        if not ok:
            self.finished_error.emit(f"No ack for line: {text} (last response: {resp})")
            return
        #sent += 1
        self.progress.emit(line, self.total)
        #if self.line_delay:
        #    time.sleep(self.line_delay)

    @QtCore.pyqtSlot()
    def stop(self):
        self._stop = True
        self.finished_error.emit('Job cancelled')
        self._running = False
        