
from PyQt5 import QtWidgets, QtCore, uic, QtGui
import os, sys

sys.path.insert(0, 'E:\Projects\Timelapse\python\lib')
sys.path.insert(0, 'E:\Projects\Moco\python\lib')


from Anim import AnimCurves
from AnimGraphicsWidgets.AnimGraphicsWidgets import *




colors = { 	'X': [1, 0, 0],
			'Y': [0, 1, 0],
			'Z': [0, 0, 1]	}

colors_int = [  [1, 0, 0],
			    [0, 1, 0],
			    [0, 0, 1]	]

class CurveViewWidget( QtWidgets.QWidget ):
    animCurveItems = dict()

    def __init__( self, parent = None):
        QtWidgets.QWidget.__init__(self, parent)
        uifile = os.path.join( os.path.dirname(__file__), 'CurveView_v001.ui')
        self.ui = uic.loadUi( uifile, self )

        self.scene = AnimGraphicsScene()
        self.ui.graphicsView.setScene( self.scene )

        self.scale = [0.035, -4]
        self.origin = [0.0, 300]		

        self.ui.listWidget.itemSelectionChanged.connect( self.enableCurves )

        #self.ui.spin_scaleX.valueChanged.connect( self.setScale )
        #self.ui.spin_scaleY.valueChanged.connect( self.setScale )

    def buildCurves( self, curves, axes ):
        self.animCurveItems = dict()
        self.ui.scene.clear()

        #for name in curves.keys():
        for i, curve in enumerate(curves):
            #axis = name.split(" \ ")[-1][0]
            #print axis
            axis = axes[i]

            item = QtWidgets.QListWidgetItem( axis )
            self.ui.listWidget.addItem(item)

            keys = []
                    
            #build curves
            self.animCurveItems[axis] = AnimCurveGraphicsItem( curve, self.scale, self.origin )
            self.animCurveItems[axis].setPenColor( colors_int[i] )
            self.animCurveItems[axis].setEnabled( False )

            self.scene.addItem( self.animCurveItems[axis] )
		
    def enableCurves( self ):
        selection = self.ui.listWidget.selectedItems()

        names = []

        for item in selection:
            names.append( item.text() )

        for curveName in self.animCurveItems.keys():
            curve = self.animCurveItems[curveName]

            if curveName in names:
                curve.setEnabled( True )
            else:
                curve.setEnabled( False )

    def setScale( self ):
        self.scale = [self.ui.spin_scaleX.value(), self.ui.spin_scaleY.value()]

        for name in self.animCurveItems.keys():
            self.animCurveItems[name].setScaleX( self.scale[0] )
            self.animCurveItems[name].setScaleY( self.scale[1] )
            self.animCurveItems[name].update()



if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    myapp = CurveViewWidget()
    myapp.show()
	
	
    sys.exit(app.exec_())				
