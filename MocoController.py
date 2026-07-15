import os, sys, ctypes


    
from PyQt5 import QtWidgets, QtCore, uic, QtGui
import serial
import serial.tools.list_ports

from lib.io.SerialManager import SerialManager, SerialSignalEmitter
from lib.io.SettingsHandler import SettingsHandler
from lib.io.GrblStatusHandler import GrblStatusHandler


#from lib.utils.GcodeJobWorker import GcodeJobWorker
#from lib.utils.GcodeStreamer import GcodeStreamer
from lib.utils.Gcode import generateGcodeFromCurves
from lib.utils.GrblSerialManager import GrblSerialManager
from lib.utils import WebPortal

import lib.utils.GrblSerial as Grbl



class MocoController( QtWidgets.QMainWindow ):
    def __init__( self, parent=None ):
        QtWidgets.QMainWindow.__init__(self, parent)

        self.settingsHandler = SettingsHandler()  
        self.grbl = GrblSerialManager()  
        self.status = GrblStatusHandler()

        self.webBridge = WebPortal.WebPortalBridge()
        self.webServer = WebPortal.WebPortalServer(self.webBridge, port=8080)
        self.webServer.start()

        self.gcodeFile = []

        uifile = os.path.join( os.path.dirname(__file__), 'ui/MocoController_v001.ui')
        self.ui = uic.loadUi( uifile, self )

        ## some weird code to set the taskbar icon
        self.setWindowIcon(QtGui.QIcon(os.path.join( os.path.dirname(__file__), 'ui/icon01.png')) )             
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('company.app.1')

        self.setWindowTitle('MocoController')
        self.ui.serialWindowWidget.toggleSendControls(False)
        self.ui.mainSplitter.setSizes([100, 1800])
        
        self.refreshPorts()
        self.connectSignals()

        ## this feels messy
        self.ui.settingsWidget.setSettingsHandler(self.settingsHandler)
        self.ui.axisReadoutWidget.setSettingsHandler(self.settingsHandler)

        self.ui.settingsWidget.setInitialSettings()        

        

    def connectSignals( self ):
        self.ui.serialConnectWidget.refreshPorts.connect( self.refreshPorts )
        self.ui.serialWindowWidget.sendLine.connect( self.sendLine )

        self.ui.serialConnectWidget.toggleConnect.connect( self.toggleConnection ) 

        self.ui.jogControlWidget.sendJogCmd.connect( self.jogAxis )
        self.ui.jogControlWidget.sendSetCmd.connect( self.setAxis )
        self.ui.jogControlWidget.sendShutterCmd.connect( self.shutter )
        self.ui.jogControlWidget.sendHomeCmd.connect( self.homeAxis )
        self.ui.jogControlWidget.sendZeroAllCmd.connect( self.zeroAll )
        self.ui.jogControlWidget.sendStopCmd.connect( self.grbl.jog_cancel)

        self.webBridge.jogRequestedDict.connect( self.jogAxis )

        self.ui.axisReadoutWidget.zeroButtonClicked.connect( self.setAxis )
        self.ui.axisReadoutWidget.homeButtonClicked.connect( self.homeAxis )

        #self.ui.serialWindowWidget.pushButton_getStatus.clicked.connect( self.getStatus )

        self.ui.serialConnectWidget.toggleGcodeProgram.connect( self.startGcodeProgram )
        self.ui.serialConnectWidget.stopGcodeProgram.connect( self.stopGcodeProgram )
        self.ui.serialConnectWidget.ui.pushButton_reset.clicked.connect( self.grbl.soft_reset )
        self.ui.serialConnectWidget.ui.pushButton_hold.clicked.connect( self.hold )

        self.ui.xafWidget.gcodeGenerated.connect( self.setGcode )
        self.ui.xafWidget.curveView.timeChangedValues.connect( self.ui.jogControlWidget.setCurveValues )

        #self.grbl.signals.message_received.connect( self.grbl_statusHandler )
        self.grbl.signals.message_received.connect( self.status.setStatus )
        self.grbl.signals.command_sent.connect( self.grbl_msgSent )
        self.grbl.signals.stream_progress.connect( self.updateSentStatus )

        ## status handlers
        self.status.wcoUpdated.connect( self.ui.axisReadoutWidget.setWcoValues ) 
        self.status.mposUpdated.connect( self.ui.axisReadoutWidget.setMposValues )        
        self.status.mainUpdated.connect( self.webBridge.update_axes_list )
        self.status.lineUpdated.connect( self.lineUpdate )
        self.status.statusUpdated.connect( self.ui.serialWindowWidget.appendStatus )


    def debugError( self, errorA=None, errorB=None ):
        if errorA is not None:
            self.ui.serialWindowWidget.appendLine( str(errorA) )
        if errorB is not None:
            self.ui.serialWindowWidget.appendLine( str(errorB) )

    ## -------------------------------------------------------------------------------------
    ## serial settings

    def refreshPorts(self):        
        ports = serial.tools.list_ports.comports()
        self.ui.serialConnectWidget.updatePorts(ports)

    def getVerbose( self ):
        return self.ui.serialWindowWidget.getVerbose()



    ## -------------------------------------------------------------------------------------
    ## serial connection stuff
        
    def toggleConnection(self):
        if not self.grbl.is_connected:
            ## connect!
            baud = self.ui.serialConnectWidget.getBaud()
            port = self.ui.serialConnectWidget.getPort()
            if not port:
                QtWidgets.QMessageBox.warning(self, 'No Port', 'Select a serial port first')
                return
            
            try:
                #self.serial_manager.open(port, baud=baud)
                self.grbl.connect( baud=baud, port=port)

                self.ui.serialConnectWidget.toggleConnectControls(True)
                self.ui.serialWindowWidget.toggleSendControls(True)
                
                #if self.getPolling():
                #    self.startPollThread(True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, 'Open Failed', f'Could not open port: {e}')
                return
        else:         
            ## disconnect       
            try:
                #self.pollingThread.stop()
                self.grbl.disconnect()
                self.ui.serialConnectWidget.toggleConnectControls(False)
                self.ui.serialWindowWidget.toggleSendControls(False)
            except Exception:
                pass


    ## -------------------------------------------------------------------------------------
    ## serial input/output

    def sendLine( self, line, echo=True ):
        self.grbl.send(line)
  
    def lineUpdate( self, line ):
        frame = max(0, line-1)/2

        self.ui.listWidget_gCode.setStatusToRow(complete=line)
        self.ui.xafWidget.curveView.current_time = frame

        targetValues = self.ui.xafWidget.getValuesAtTime(frame)
        self.ui.axisReadoutWidget.setTargetValues(targetValues)


    def grbl_msgSent( self, line ):
        self.ui.serialWindowWidget.appendLine("TX | " + line)

    def updateSentStatus( self, sent, total=0 ):
        self.ui.listWidget_gCode.setStatusToRow(sent=sent)

    ## -------------------------------------------------------------------------------------
    ## commands from jog controls

    def jogAxis( self, jogData ):
        jogGcode = Grbl.generateJogCmd(jogData, self.settingsHandler, self.status )       
        self.grbl.send(jogGcode)    

    def setAxis( self, axis, val=0 ):
        gcode = Grbl.setAxisCmd( axis, val, self.settingsHandler )
        self.grbl.send(gcode)
        
    def homeAxis( self, axis=None ):
        gcode = Grbl.generateHomeCmd( axis )
        self.grbl.send(gcode)
        
    def zeroAll( self ):        
        self.grbl.set(x=0,y=0,z=0,a=0,b=0)

    def shutter( self, tog ):        
        gcode = Grbl.cameraCmd(tog)
        self.grbl.send(gcode)

    def hold( self, tog ):
        if tog:            
            self.grbl.feed_hold()
        else:
            self.grbl.cycle_start()

    def reset( self ):        
        self.grbl.soft_reset()

    ## -------------------------------------------------------------------------------------
    ## gcode & worker stuff

    def startGcodeProgram( self ):
        #self.gcode_streamer.toggleStream(True)
        if len(self.gcodeFile)>0:
            self.grbl.stream_commands(self.gcodeFile)


    def stopGcodeProgram( self ):
        #self.gcode_streamer.toggleStream(False)
        #self.gcode_streamer.addCmdLine(1, "M02")
        return

    def setGcode( self, file ):
        self.ui.listWidget_gCode.setGcode(file)
        self.gcodeFile = file
        self.dumpGcodeFile(file)

    def parseGcodeFile( self ):
        filename = 'anim_test_v002.gcode'
        file = []
        f = open(filename, "r")        

        for line in f.readlines():
            line = line.strip("\r\n ")            
            file.append(line)

        #self.gcode_streamer.setGcode(file)
        self.debugError( "parsed gcode!" )
        return file

    def dumpGcodeFile( self, gcode ):
        filename = 'anim_test_v002.gcode'

        f = open(filename, "w")
        
        for line in gcode:
            f.write(line+"\n")



if __name__ == "__main__":
    import qt_themes

    app = QtWidgets.QApplication(sys.argv)
    qt_themes.set_theme("blender")
    myapp = MocoController()
    myapp.showMaximized()
    
    
    sys.exit(app.exec_())               
