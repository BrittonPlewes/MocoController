import os, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui



class SerialConnectWidget( QtWidgets.QWidget ):
    toggleConnect       = QtCore.pyqtSignal()    
    refreshPorts        = QtCore.pyqtSignal()
    toggleGcodeProgram  = QtCore.pyqtSignal( bool )
    stopGcodeProgram    = QtCore.pyqtSignal()

    def __init__( self, parent=None ):
        QtWidgets.QWidget.__init__(self, parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/SerialConnect_v001.ui')
        self.ui = uic.loadUi( uifile, self )    

        self.ui.comboBox_baud.setCurrentIndex(4)
        self.toggleConnectControls(False)

        self.connected = False

        self.connectSignals()

    def connectSignals( self ):
        self.ui.pushButton_connect.clicked.connect( self.toggleConnect.emit )
        self.ui.pushButton_refresh.clicked.connect( self.refreshPorts.emit )

        self.ui.pushButton_play.clicked.connect( self.toggleGcodeProgram.emit )
        self.ui.pushButton_stop.clicked.connect( self.stopGcodeProgram.emit )

    def toggleConnectControls( self, tog ):
        buttonText = ["Connect!", "Disconnect"]
        self.ui.pushButton_connect.setText( buttonText[tog] )
        self.ui.frameControls.setEnabled(1-tog)
        self.ui.framePlayControls.setEnabled(tog)        


    def togglePlayControls( self, tog ):
        self.ui.framePlayControls.setEnabled(tog)

    def updatePorts( self, ports ):
        self.ui.comboBox_port.clear()
        
        for p in ports:
            self.ui.comboBox_port.addItem(p.device)

    def getPort( self ):
        return self.ui.comboBox_port.currentText()
    
    def getBaud( self ):
        return int( self.ui.comboBox_baud.currentText() )

    def setProgressRange( self, range ):
        self.ui.progressBar.setMinimum(range[0])
        self.ui.progressBar.setMaximum(range[1])

    def setProgress( self, val ):
        self.ui.progressBar.setValue(int(val))


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    myapp = SerialConnectWidget()
    myapp.show()
    
    sys.exit(app.exec_())               
