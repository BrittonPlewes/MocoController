import os, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui



class JogControlWidget( QtWidgets.QWidget ):
    jogValues = [0, 1, 5, 10, 15, 30, 45, 60, 90]
    jogSpeeds = [0, 0.1, 0.25, 0.5, 1, 2.5, 5, 7.5, 10, 15, 20]    

    sendJogCmd      = QtCore.pyqtSignal(dict)    
    sendSetCmd      = QtCore.pyqtSignal(int,float)
    sendMultiSetCmd = QtCore.pyqtSignal(list, list)
    sendShutterCmd  = QtCore.pyqtSignal(bool)
    sendHomeCmd     = QtCore.pyqtSignal()
    sendZeroAllCmd  = QtCore.pyqtSignal()
    sendStopCmd     = QtCore.pyqtSignal()

    def __init__( self, parent=None ):
        QtWidgets.QWidget.__init__(self, parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/JogControls_v001.ui')
        self.ui = uic.loadUi( uifile, self )        

        self.jogButtonGroup = QtWidgets.QButtonGroup()
        self.goButtonGroup = QtWidgets.QButtonGroup()
        self.setButtonGroup = QtWidgets.QButtonGroup()
        self.modeButtonGroup = QtWidgets.QButtonGroup()

        self.jogButtonGroup.addButton( self.ui.pushButton_xPos, 0 )
        self.jogButtonGroup.addButton( self.ui.pushButton_xNeg, 1 )
        self.jogButtonGroup.addButton( self.ui.pushButton_yPos, 2 )
        self.jogButtonGroup.addButton( self.ui.pushButton_yNeg, 3 )
        self.jogButtonGroup.addButton( self.ui.pushButton_zPos, 4 )
        self.jogButtonGroup.addButton( self.ui.pushButton_zNeg, 5 )
        self.jogButtonGroup.addButton( self.ui.pushButton_aPos, 6 )
        self.jogButtonGroup.addButton( self.ui.pushButton_aNeg, 7 )
        self.jogButtonGroup.addButton( self.ui.pushButton_bPos, 8 )
        self.jogButtonGroup.addButton( self.ui.pushButton_bNeg, 9 )        

        self.goButtonGroup.addButton( self.ui.pushButton_goX, 0 )
        self.goButtonGroup.addButton( self.ui.pushButton_goY, 1 )
        self.goButtonGroup.addButton( self.ui.pushButton_goZ, 2 )
        self.goButtonGroup.addButton( self.ui.pushButton_goA, 3 )
        self.goButtonGroup.addButton( self.ui.pushButton_goB, 4 )
        
        self.setButtonGroup.addButton( self.ui.pushButton_setX, 0 )
        self.setButtonGroup.addButton( self.ui.pushButton_setY, 1 )
        self.setButtonGroup.addButton( self.ui.pushButton_setZ, 2 )
        self.setButtonGroup.addButton( self.ui.pushButton_setA, 3 )
        self.setButtonGroup.addButton( self.ui.pushButton_setB, 4 )      

        self.modeButtonGroup.addButton( self.ui.radioButton_manual, 0 )
        self.modeButtonGroup.addButton( self.ui.radioButton_curves, 1 )

        self.axisChecks = [
            self.ui.checkBox_X,
            self.ui.checkBox_Y,
            self.ui.checkBox_Z,
            self.ui.checkBox_A,
            self.ui.checkBox_B
        ]

        self.axisSpinBoxes = [
            self.ui.spin_X,
            self.ui.spin_Y,
            self.ui.spin_Z,
            self.ui.spin_A,
            self.ui.spin_B
        ]                  

        self.connectSignals()
        self.updateJogSpeed( self.ui.slider_jogSpeed.value() )
        self.updateJogAmt( self.ui.slider_jogAmt.value() )

    def connectSignals( self ):
        self.jogButtonGroup.idClicked.connect( self.triggerJogCommand )
        self.goButtonGroup.idClicked.connect( self.triggerGoCommand )
        self.setButtonGroup.idClicked.connect( self.triggerSetCommand )
        self.modeButtonGroup.idClicked.connect( self.setManualMode )

        self.ui.slider_jogAmt.valueChanged.connect( self.updateJogAmt )
        self.ui.slider_jogSpeed.valueChanged.connect( self.updateJogSpeed )

        #self.ui.pushButton_shutter.toggled.connect( self.sendShutterCmd.emit )
        self.ui.pushButton_shutter.pressed.connect( self.triggerShutterCmd )
        self.ui.pushButton_shutter.released.connect( self.triggerShutterCmd )
        self.ui.pushButton_home.clicked.connect( self.sendHomeCmd.emit )
        self.ui.pushButton_zeroAll.clicked.connect( self.sendZeroAllCmd.emit )

        self.ui.pushButton_goAll.clicked.connect( self.triggerGoMulti )
        self.ui.pushButton_setAll.clicked.connect( self.triggerSetMulti )

        self.ui.pushButton_stop.clicked.connect( self.sendStopCmd )

    def updateJogAmt( self, value ):
        self.ui.spinBox_jogAmt.setValue( self.jogValues[value] )

    def updateJogSpeed( self, value ):
        self.ui.spinBox_jogSpeed.setValue( self.jogSpeeds[value])

    def triggerJogCommand( self, id ):
        jogData = dict()
        jogData['abs'] = False
        jogData['amount'] = self.jogValues[self.ui.slider_jogAmt.value()]
        jogData['feedrate'] = self.jogSpeeds[self.ui.slider_jogSpeed.value()]*60

        if id%2 != 0:
            jogData['amount'] *= -1

        jogData['axis'] = int(id/2)

        self.sendJogCmd.emit(jogData)

    def triggerGoCommand( self, id ):
        jogData = dict()
        jogData['abs'] = True
        jogData['amount'] = self.axisSpinBoxes[id].value()
        jogData['feedrate'] = self.jogSpeeds[self.ui.slider_jogSpeed.value()]*60
        jogData['axis'] = id

        self.sendJogCmd.emit(jogData)


    def triggerSetCommand( self, id ):
        val = self.axisSpinBoxes[id].value()
        self.sendSetCmd.emit(id, val)

    def triggerGoMulti( self ):
        axes = self._getChecks()
        jogData = dict()
        jogData['abs'] = True
        jogData['feedrate'] = self.jogSpeeds[self.ui.slider_jogSpeed.value()]*60
        jogData['amount'] = []
        jogData['axis'] = axes
        
        for i, axis in enumerate(axes):
            val = self.axisSpinBoxes[axis].value()
            jogData['amount'].append(val)

        self.sendJogCmd.emit(jogData)
    
    def triggerSetMulti( self ):
        axes = self._getChecks()
        vals = []
        for i, axis in enumerate(axes):
            val = self.axisSpinBoxes[axis].value()
            vals.append(val)

        self.sendMultiSetCmd.emit(axes, vals)        


    def triggerShutterCmd( self ):
        val = self.ui.pushButton_shutter.isDown()
        self.sendShutterCmd.emit(val)


    def setManualMode( self, mode ):
        for spin in self.axisSpinBoxes:
            spin.setEnabled(1-mode)
        
    def setCurveValues( self, values ):
        if self.modeButtonGroup.checkedId() == 1:
            for i in range(min(len(values), len(self.axisSpinBoxes))):
                self.axisSpinBoxes[i].setValue(values[i])

    def _getChecks( self ):
        checks = []
        for i, chk in enumerate(self.axisChecks):
            if chk.isChecked():
                checks.append(i)
        return checks


if __name__ == "__main__":
    import qt_themes

    app = QtWidgets.QApplication(sys.argv)
    qt_themes.set_theme("blender")    
    myapp = JogControlWidget()
    myapp.show()
    
    
    sys.exit(app.exec_())               
