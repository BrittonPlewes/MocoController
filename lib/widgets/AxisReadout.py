import os, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui




class AxisReadoutWidget( QtWidgets.QWidget ):
    zeroButtonClicked = QtCore.pyqtSignal(int)
    homeButtonClicked = QtCore.pyqtSignal(int)

    def __init__( self, parent=None ):
        super().__init__(parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/AxisReadout_v001.ui')
        self.ui = uic.loadUi( uifile, self )  

        self.settingsHandler = None                  

        self.zeroButtonGroup = QtWidgets.QButtonGroup()
        self.zeroButtonGroup.addButton( self.ui.pushButton_zeroX, 0 )
        self.zeroButtonGroup.addButton( self.ui.pushButton_zeroY, 1 )
        self.zeroButtonGroup.addButton( self.ui.pushButton_zeroZ, 2 )
        self.zeroButtonGroup.addButton( self.ui.pushButton_zeroA, 3 )
        self.zeroButtonGroup.addButton( self.ui.pushButton_zeroB, 4 )        

        self.homeButtonGroup = QtWidgets.QButtonGroup()
        self.homeButtonGroup.addButton( self.ui.pushButton_homeX, 0 )
        self.homeButtonGroup.addButton( self.ui.pushButton_homeY, 1 )
        self.homeButtonGroup.addButton( self.ui.pushButton_homeZ, 2 )
        self.homeButtonGroup.addButton( self.ui.pushButton_homeA, 3 )
        self.homeButtonGroup.addButton( self.ui.pushButton_homeB, 4 )        

        self.zeroButtonGroup.idClicked.connect( self.zeroButtonClicked.emit )
        self.homeButtonGroup.idClicked.connect( self.homeButtonClicked.emit )

        self.axesLcds = [   self.ui.graphicsView_xAxis,
                            self.ui.graphicsView_yAxis, 
                            self.ui.graphicsView_zAxis,
                            self.ui.graphicsView_aAxis,
                            self.ui.graphicsView_bAxis ]   

        self.rawWcos = [0,0,0,0,0]

        self._numAxes = len(self.axesLcds)

        for i, widget in enumerate(self.axesLcds):     
            widget.setAxis(i)


    def adjustInputValue( self, axis, value ):
        if self.window() is not None:
            if self.window().settingsHandler is not None:
                value = self.window().settingsHandler.getAxisInputValue( axis, value )
        return value

    def setMposValue( self, axis, value ):        
        self.axesLcds[axis].setMposValue(self.adjustInputValue(axis, value))
        

    def setWcoValue( self, axis, value ):
        self.rawWcos[axis] = value
        self.axesLcds[axis].setWcoValue(self.adjustInputValue(axis, value))
        #self.axesLcds[axis].setWcoValue(value)

    def setTargetValue( self, axis, value ):                
        self.axesLcds[axis].setTargetValue(self.adjustInputValue(axis, value))
        #self.axesLcds[axis].setTargetValue(value)

    def setWcoValues( self, values):
        i = min(self._numAxes, len(values))       
        for axis, value in enumerate(values[:i]):
            self.setWcoValue(axis, value)

    def setMposValues( self, values ):
        i = min(self._numAxes, len(values))    
        for axis, value in enumerate(values[:i]):
            self.setMposValue(axis, value)

    def setTargetValues( self, values ):
        i = min(self._numAxes, len(values))
        for axis, value in enumerate(values[:i]):
            self.setTargetValue(axis, value)
        
    def setSettingsHandler( self, handler ):
        self.settingsHandler = handler

        for axis, lcd in enumerate( self.axesLcds ):
            if len(self.settingsHandler.axes) > axis:
                settings = self.settingsHandler.axes[axis]

                settings.absSet.connect( lcd.toggleAbs )
                settings.unitSet.connect( lcd.setUnit )







if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    myapp = AxisReadoutWidget()
    myapp.show()
    myapp.setAxesValues([0.2, 5.0, 9.1010101])
    
    sys.exit(app.exec_())               
