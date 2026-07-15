import os, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui




class SerialWindowWidget( QtWidgets.QWidget ):
    sendLine = QtCore.pyqtSignal( str )    
    pollingToggled = QtCore.pyqtSignal( bool )
    pollrateUpdated = QtCore.pyqtSignal( int )

    def __init__( self, parent=None ):
        QtWidgets.QWidget.__init__(self, parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/SerialWindow_v001.ui')
        self.ui = uic.loadUi( uifile, self )    
    
        self.togglePolling(self.ui.checkBox_poll.isChecked())

        self.connectSignals()

    def connectSignals( self ):
        self.ui.lineEdit.returnPressed.connect( self._sendLine )
        self.ui.pushButton_send.clicked.connect( self._sendLine )
        self.ui.checkBox_poll.clicked.connect( self.togglePolling )
        self.ui.spinBox_pollRate.valueChanged.connect( self.pollrateUpdated.emit )
        self.ui.pushButton_clear.clicked.connect( self.ui.serialTextWindow.clear )
        #self.ui.pushButton_getStatus.clicked.connect( self.)


    def appendStatus( self, line ):
        if self.getVerbose():
            self.appendLine( line )

    def appendLine( self, line ):
        self.ui.serialTextWindow.appendPlainText( line )

    def toggleSendControls( self, tog ):
        self.ui.sendControlsFrame.setEnabled(tog)
   
    def togglePolling( self, tog ):
        self.ui.frameControls.setEnabled(tog)
        self.pollingToggled.emit( tog )


    def _sendLine( self ):
        line = self.ui.lineEdit.text()        
        self.ui.lineEdit.setText("")
        self.sendLine.emit(line)        

    def getVerbose( self ):
        return self.ui.checkBox_verbose.isChecked()
    
    def getPollRate( self ):
        return self.ui.spinBox_pollRate.value()
    
    def getPolling( self ):
        return self.ui.checkBox_poll.isChecked()



if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    myapp = SerialWindowWidget()
    myapp.show()
    
    sys.exit(app.exec_())               
