import os, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui


#sys.path.append( "E:/Projects/Moco/python/lib/")

from lib.io.SettingsHandler import SettingsHandler

class SettingsViewWidget( QtWidgets.QWidget ):
    

    def __init__( self, parent=None ):
        super().__init__(parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/SettingsView_v001.ui')
        self.ui = uic.loadUi( uifile, self )

        self.handler: SettingsHandler = None

        self.axisSettings = [
            self.ui.widget_axisSettings01,
            self.ui.widget_axisSettings02,
            self.ui.widget_axisSettings03,
            self.ui.widget_axisSettings04,
            self.ui.widget_axisSettings05
        ]

        for i, axis in enumerate(self.axisSettings):
            axis.setAxis(i)

    def setInitialSettings( self ):
        ## gotta fix this later
        self.axisSettings[3].setUnit(1)
        self.axisSettings[3].toggleXaf(True)
        self.axisSettings[3].toggleAbs(True)        
        self.axisSettings[3].setOffset(0.0)
        
        self.axisSettings[4].setUnit(1)
        

    def setSettingsHandler( self, handler: SettingsHandler):
        self.handler = handler

        if self.handler.numAxes() > 0:
            for axis, settings in enumerate(self.handler.axes):
                ui = self.axisSettings[axis]
                
                ui.reverseUpdated.connect( settings.setRev )
                ui.absUpdated.connect( settings.setAbs )
                ui.useCurveUpdated.connect( settings.toggleCurve )
                ui.curveUpdated.connect( settings.setAxisCurve )
                ui.unitUpdated.connect( settings.setUnit )

                ui.emitSettings()

    def getSettingsHandler( self ):
        return self.handler
        
        
            


if __name__ == "__main__":
    import qt_themes
    app = QtWidgets.QApplication(sys.argv)
    qt_themes.set_theme("blender")
    myapp = SettingsViewWidget()
    myapp.show()
    
    sys.exit(app.exec_())               
