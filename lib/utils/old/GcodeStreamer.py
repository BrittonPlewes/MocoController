import os, sys, time


if sys.platform == "win32":
    sys.path.insert( 0, "E:/Projects/Moco/python/lib")

import queue
import itertools
import threading
from pathlib import Path

from SerialManager import SerialManager


class GcodeStreamer(object):
    def __init__(self, serial_manager: SerialManager, parent=None,
                 pgmCmd_callback=None,
                 line_delay=0.05, ack_timeout=5.0):

        self.serial = serial_manager
        self.line_delay = line_delay
        self.ack_timeout = ack_timeout

        self.counter = itertools.count()        
        self.cmd_queue = queue.PriorityQueue()
        self.pgm_queue = queue.PriorityQueue()
        self.next_cmd = None

        self.verbose = True

        self.pgmCmd_callback = pgmCmd_callback

        self.bufferSpace = [100,1023]

        self._running = threading.Event()
        self._streaming = False #3 threading.Event()
        self._thread = None

    def setBuffer( self, bf ):
        self.bufferSpace = bf

    def getStatus( self ):
        self.addGcodeCmd(1, "??")

    def clearQueue( self ):
        try:
            while True:
                self.pgm_queue.get_nowait()
        except queue.Empty:
            pass

    def setGcode( self, lines ):        
        self.clearQueue()        
        for i, line in enumerate(lines):
            self.addPgmLine(5, line, gcodeLine=i)

    def addPgmLine( self, prio, cmd, gcodeLine=-1 ):
        self.pgm_queue.put( (prio, gcodeLine, cmd) )

    def addCmdLine( self, prio, cmd ):
        self.cmd_queue.put( (prio, next(self.counter), cmd) )

    def toggleStream( self, tog ):
        print( "toggle stream")
        if tog:
            self._streaming = True #.set()
        else:
            self._streaming = False #.clear()

    def _write_Loop( self ):
        while self._running.is_set():

            ## if immediate queued tasks are pending
            if not self.cmd_queue.empty():                
                if self.bufferSpace[1] >= 10:
                    cmd = self.cmd_queue.get()
                    
                    if self.verbose:
                        self.serial.on_line(cmd[2])

                    #self.serial.send_line( cmd[2] )                       
                    ack = self.serial.send_and_wait_ack(    cmd[2], 
                                                            self.ack_timeout )
                    
                    if not ack[0]:
                        self._running.clear()
                        self.serial.on_line('stopping! no acknowledgement from serial')
                        break

                    #time.sleep(self.line_delay)
                continue
            
            ## if gcode queued tasks are pending
            if self._streaming and not self.pgm_queue.empty():
                if self.bufferSpace[0] > 1:
                    
                    ## get first command if stream has just started                    
                    if self.next_cmd is None:
                        self.next_cmd = self.pgm_queue.get()

                    if self.bufferSpace[1] > len(self.next_cmd[2]):     
                        
                        if self.verbose:
                            self.serial.on_line(self.next_cmd[2])

                        ack = self.serial.send_and_wait_ack(    self.next_cmd[2], 
                                                                self.ack_timeout )

                        if not ack[0]:
                            self._running.clear()
                            self.serial.on_line('stopping! no acknowledgement from serial')
                            break
                        
                        self.pgmCmd_callback( self.next_cmd[1] )

                        self.bufferSpace[0] -= 1
                        self.bufferSpace[1] -= len(self.next_cmd[2])
                        
                        time.sleep(self.line_delay)

                        ## we take it out of the queue a loop ahead 
                        ## in order to check rx buffer space
                        self.next_cmd = self.pgm_queue.get()

                continue            
            
            time.sleep(0.1)

    def start( self ):        
        self._running.set()
        self._streaming=False
        self._thread = threading.Thread(target=self._write_Loop, daemon=True)
        self._thread.start()
        
        