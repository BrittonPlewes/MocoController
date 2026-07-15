import serial
import threading
import time
import itertools
import queue

from GrblSerial import parseGrblStatus


class GrblSerialManager(object):

    def __init__(   self, rx_callback=None,
                    tx_callback=None,
                    status_callback=None,
                    debug_callback=None):
        
        self.serial = serial.Serial()
        self.rx = rx_callback
        self.tx = tx_callback
        self.status = status_callback
        self.debug = debug_callback

        self.verbose = False

        self.ack_timeout = 5.0
        self.tx_thread_delay = 0.25
        self.poll_delay = 0.5
        self._last_response = None

        self.counter = itertools.count()        
        self.cmd_queue = queue.PriorityQueue()
        self.pgm_queue = queue.PriorityQueue()
        self.next_cmd = None

        self.bufferSpace = [100,1023]
        
        self._rx_running = threading.Event()
        self._tx_running = threading.Event()
        self._polling = threading.Event()
        self._stream_running = threading.Event()
        self._serial_lock = threading.Lock()
        self._ack_event = threading.Event()

        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)


    ## ---------------------------------------------------------------
    ## connection stuff

    def open( self, port, baud=115200, timeout=0.1 ):
        if self.is_open():
            raise RuntimeError('already open')
        
        self.debug("opening connection")

        self.serial.baudrate = baud
        self.serial.port = port
        self.serial.write_timeout=0.1

        self.serial.open()      
  
        if self.is_open():
            self._rx_running.set()               
            self._tx_running.set()
            self._polling.set()

            self.rx_thread.start()
            self.tx_thread.start()
            self.poll_thread.start()

            self._ack_event.set()
        

    def close(self):
        if self.is_open():
            try:
                self.serial.close()
                self.rx_thread.stop()
                self._running.clear()
            except Exception:
                pass                  

    def is_open(self):
        return self.serial.is_open

    def is_streaming(self):
        return self._stream_running.is_set()

    ## ---------------------------------------------------------------
    ## serial communication stuff

    def send_line( self, line: str, add_newline=True):
        ## cleanup
        line = (line + ('\r\n' if add_newline else '')).encode('utf-8')
        
        #with self._serial_lock:
        if not self.is_open():
            raise RuntimeError('serial port not open')                

        self.serial.write(line)
        self.serial.flush()
     

    def send_and_wait_ack( self, line: str, timeout=2.0 ):
        self._ack_event.clear()

        try:
            self.send_line(line, add_newline=True)            
        except Exception as e:
            return False, f"<send error> {e}"
        
        waited = self._ack_event.wait(timeout)
        return bool(waited), self._last_response


    def write_raw(self, data: bytes):        
        with self._serial_lock:    
            if not self.is_open():
                raise RuntimeError('serial port not open')
                
            self.serial.write(data)
            self.serial.flush()        

    ## ---------------------------------------------------------------
    ## command stuff

    def set_bufferSpace( self, data ):
        self.bufferSpace = data

    def set_verbose(self, verbose: bool ):
        self.versbose = verbose

    def set_polling_delay( self, poll: float):
        self.poll_delay = poll

    def clearPgmQueue( self ):
        ## dump all commands from program queue
        try:
            while True:
                self.pgm_queue.get_nowait()
        except queue.Empty:
            pass

    def addPgmLine( self, cmd: str, prio=0, gcodeLine=-1 ):
        ## add line to gcode stream
        self.pgm_queue.put( (prio, gcodeLine, cmd) )

    def addCmdLine( self, cmd: str, prio=0 ):
        ## add command for immediate use
        self.cmd_queue.put( (prio, next(self.counter), cmd) ) 

    def toggleStream( self, tog ):
        if tog:
            self._stream_running.set()
        else:
            self._stream_running.clear()

    def togglePolling( self, tog ):
        if tog:
            self._polling.set()
        else:
            self._polling.clear()

    ## ---------------------------------------------------------------
    ## thread/looping stuff

    def _tx_loop(self):
        while self._tx_running.is_set():                     
            ## if immediate queued tasks are pending
            if not self.cmd_queue.empty():                
                if self.bufferSpace[1] >= 10:
                    cmd = self.cmd_queue.get()                   

                    self.tx(cmd[2])
                    ack = self.send_and_wait_ack(   cmd[2], 
                                                    self.ack_timeout )
                    
                    if not ack[0]:
                        self._tx_running.clear()
                        self.debug('stopping! no acknowledgement from serial')
                        break
                    else:
                        if self.verbose:
                            self.tx( ( cmd[2] + ": " + str(ack[0]) + " - " + ack[1] ) )
                    
                continue
            
            ## if gcode queued tasks are pending
            if self._stream_running.is_set() and not self.pgm_queue.empty():
                ## if estimated planner queue has space
                if self.bufferSpace[0] > 5:
                    
                    ## get first command if stream has just started                    
                    if self.next_cmd is None:
                        self.next_cmd = self.pgm_queue.get()

                    ## if enough RX buffer space on grbl
                    if self.bufferSpace[1] > len(self.next_cmd[2])+20:     
                        
                        self.tx(self.next_cmd[2])
                        ack = self.send_and_wait_ack(    self.next_cmd[2], 
                                                                self.ack_timeout )

                        if not ack[0]:
                            self._tx_running.clear()
                            self.debug('stopping! no acknowledgement from serial')
                            break
                        else:
                            if self.verbose:                                           
                                self.tx( ( self.next_cmd[2] + ": " + str(ack[0]) + " - " + ack[1] )  )


                        ## adjust bufferspace predictions
                        self.bufferSpace[0] -= 1
                        self.bufferSpace[1] -= len(self.next_cmd[2])
                        
                        
                        ## we take it out of the queue a loop ahead 
                        ## in order to check rx buffer space
                        self.next_cmd = self.pgm_queue.get()

                        ## pause some predetermined time
                        #time.sleep(self.tx_thread_delay)
                continue            
            



    def _rx_loop(self):
        while self._rx_running.is_set():                                   
            try:                       
                if not self.is_open():                    
                    self._rx_running.clear()
                    break
                
                if self.serial.in_waiting == 0:
                    continue

                ## take control of Serial and get the data                
                with self._serial_lock: 
                    raw = self.serial.readline()
                
                ## deal with the data
                if not raw:                    
                    continue
                try:
                    line = raw.decode(errors='ignore').rstrip('\r\n')
                except Exception:
                    line = repr(raw)                    

                # check for ack tokens
                low = line.lower().strip()
                if 'ok' in low or 'error' in low or 'alarm' in low or 'grblhal' in low:
                    # set ack event and stash response
                    self._last_response = line
                    self._ack_event.set()
                elif low[0] == "<" and low[-1] == ">":
                    data = parseGrblStatus(line)
                    if 'Bf' in data:
                        self.set_bufferSpace(data['Bf'])

                    ## send parsed status to callback
                    self.status(data)

                ## send data to callback                
                self.rx( line )

                        
            except serial.SerialException as e:
                if self.debug:
                    self.debug(f"<serial error> {e}")
                self._rx_running.clear()
                break

    def _poll_loop(self):
        while self._polling.is_set():
            # don't bother unless we're actually running
            if self._tx_running.is_set():               
                self.addCmdLine("?")                
                

            time.sleep(self.poll_delay)

            continue



            