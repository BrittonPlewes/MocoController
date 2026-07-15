import os, sys

#sys.path.append( "E:/Projects/Moco/python/lib/")

from PyQt5 import QtWidgets, QtCore, uic, QtGui

from lib.utils import XafFile
from lib.utils.AnimCurve import AnimCurve, KeyFrame


class AxisSettingsWidget( QtWidgets.QWidget ):
    reverseUpdated = QtCore.pyqtSignal( bool )
    absUpdated = QtCore.pyqtSignal( bool )
    useCurveUpdated = QtCore.pyqtSignal( bool )
    curveUpdated = QtCore.pyqtSignal( AnimCurve )
    unitUpdated = QtCore.pyqtSignal( int )

    def __init__( self, parent=None ):
        super().__init__(parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/AxisSettings_v001.ui')
        self.ui = uic.loadUi( uifile, self )    

        self.axis = 0

        axisCurvesPath = os.path.join( os.path.dirname(__file__), 'xaf/lens_curves_v002.xaf')
        ## parse/sort the Xaf lens curve file
        self.XafFile = XafFile.ParseXAF(axisCurvesPath)
        self.XafFileCurves = XafFile.keysToCurves(self.XafFile)   
        
        self.ui.combo_xaf_mult_controller.addItems( self.XafFile['controllers'].keys() )
        
        self._updateUnit()

        self.connectSignals()

        self.toggleXaf(False)


    ## -------------------------------------------------------------------------------------
    ## signals

    def connectSignals( self ):             
        self.ui.checkBox_xaf.toggled.connect(self.toggleXaf)
        self.ui.checkBox_rev.toggled.connect( self.reverseUpdated.emit )
        self.ui.checkBox_abs.toggled.connect( self.absUpdated.emit )
        self.ui.combo_xaf_mult_controller.currentIndexChanged.connect( self.curveChanged )
        self.ui.comboBox_unit.currentIndexChanged.connect( self._updateUnit )
        self.ui.comboBox_unit.currentIndexChanged.connect( self.unitUpdated.emit )        
        #self.ui.groupBox_header.toggled.connect(self.toggleControls)

        self.ui.spinBox_xafOffset.valueChanged.connect( self._updateOffset )

    def emitSettings( self ):
        self.reverseUpdated.emit( self.ui.checkBox_rev.isChecked() )
        self.useCurveUpdated.emit( self.useXaf )

        if self.useXaf:
            self.curveUpdated.emit( self.getCurve() )

    ## -------------------------------------------------------------------------------------
    ## base settings

    def setAxis( self, axis ):
        axes = "XYZABCUVW"
        self.axis = axis
        self.ui.groupBox_header.setTitle(axes[axis]+" Axis")

    def toggleXaf( self, tog ):        
        ## disconnect signals so this function can be used externally without looping
        self.ui.checkBox_xaf.toggled.disconnect(self.toggleXaf)
        self.ui.checkBox_xaf.setChecked(tog)
        self.ui.checkBox_xaf.toggled.connect(self.toggleXaf)        

        ## adjust interface
        self.ui.combo_xaf_mult_controller.setEnabled(tog)
        self.ui.spinBox_xafOffset.setEnabled(tog)
        self.ui.label_offset.setEnabled(tog)
        self.useXaf = tog

        self.useCurveUpdated.emit(self.useXaf)
        self.curveChanged()   

    def toggleAbs( self, tog ):
        self.ui.checkBox_abs.setChecked(tog)

    def setUnit( self, unit ):
        self.ui.comboBox_unit.setCurrentIndex(unit)

    def setOffset( self, offset ):
        self.ui.spinBox_xafOffset.setValue(offset)

    def toggleControls( self, tog ):
        sizes = [20,999]
        self.ui.frame.setVisible(tog)
        self.ui.groupBox_header.setMaximumSize(1677215, sizes[tog])        
        self.updateGeometry()

    def _updateUnit( self ):
        unit = self.ui.comboBox_unit.currentText()

        self.ui.label_travel_unit.setText(f"step/{unit}")
        self.ui.label_max_unit.setText(f"{unit}/min")
        self.ui.label_accel_unit.setText(f"{unit}/sec^2")
        self.ui.label_maxTravel_unit.setText(unit)

    def _updateOffset( self, offset ):
        self.getCurve().t_offset = offset

        self.curveChanged()

    ## -------------------------------------------------------------------------------------
    ## xaf file stuff

    def getCurve( self ):
        index = self.ui.combo_xaf_mult_controller.currentIndex()
        return self.XafFileCurves[index]

    def curveChanged( self ):        
        self.curveUpdated.emit(self.getCurve())


    

if __name__ == "__main__":
    import qt_themes
    app = QtWidgets.QApplication(sys.argv)
    qt_themes.set_theme("blender")
    myapp = AxisSettingsWidget()
    myapp.show()
    
    sys.exit(app.exec_())               
