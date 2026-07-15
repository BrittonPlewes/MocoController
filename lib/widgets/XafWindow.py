import os, sys

#sys.path.append( "E:/Projects/Moco/python/lib/")


from PyQt5 import QtWidgets, QtCore, uic, QtGui
from math import ceil

import lib.utils.XafFile as XafFile
from lib.utils.AnimCurve import AnimCurve, KeyFrame
from lib.widgets.AnimCurveEditor import AnimCurveEditor


from lib.utils.Gcode import generateGcodeFromCurves
#from MocoWidgets.GcodeListWidget import GcodeListWidgetItem


## -------------------------------------------------------------------------------------
## exposure value helper

def getExposure( i ):     
    EXPOSURE_STR = ["1/500", "1/400", "1/320", "1/250", "1/200", "1/160", "1/125",
                    "1/100", "1/80",  "1/60",  "1/50",  "1/40",  "1/30",  "1/25",
                    "1/20",  "1/15",  "1/13",  "1/10",  "1/8",   "1/6",   "1/5",
                    "1/4",   "0.3",   "0.4",   "0.5",   "0.6",   "0.8",   "1",
                    "1.3",   "1.6",   "2",     "2.5",   "3.2",   "4",     "5",
                    "6",     "8",     "10",    "13",    "15",    "20",    "25",
                    "30" ]
    
    EXPOSURE_MILLIS = []

    for exp in EXPOSURE_STR:
        if "/" in exp:
            time = ceil(1000.0/float( exp.split("/")[1]))
        else:
            time = ceil(1000*float(exp))

        EXPOSURE_MILLIS.append(time)

    exp = dict()
    exp['str'] = EXPOSURE_STR[i]
    exp['millis'] = EXPOSURE_MILLIS[i]
    
    return exp



def frameRangeInTicks( tpf, range ):
    ## prep the list of frames in ticks
    times = []
    t=range[0]
    while t <= range[1]:
        times.append(t)
        t+=tpf

    return times

def getMaxDelta( curve, tpf, range ):    
    ## prep the list of frames in ticks
    times = frameRangeInTicks(tpf, range)    

    values = []
    i=0 

    for i, t in enumerate(times[:-1]):        
        values.append( abs(curve.evaluate(times[i+1]-1)-curve.evaluate(times[i])) )

    return max(values)

    

        
def getFeedRate( dist, time ):
    ## returning degrees/min (stupid grbl)
    return ((60*1000)/time) * dist




## -------------------------------------------------------------------------------------
## QWidget

class XafWindowWidget( QtWidgets.QWidget ):
    gcodeGenerated = QtCore.pyqtSignal( list )
    curvesUpdated = QtCore.pyqtSignal()

    def __init__( self, parent=None ):
        QtWidgets.QWidget.__init__(self, parent)
        uifile = os.path.join( os.path.dirname(__file__), 'ui/XafWindow_v001.ui')
        self.ui = uic.loadUi( uifile, self )    
    
        self.curveView = AnimCurveEditor()
        self.ui.verticalLayout_curveView.addWidget(self.curveView)        

        self.SHOT_FOLDER = "E:/Projects/MoCo/shots"
        self.XafFile = None
        self.XafFileCurves = []

        self.frames = 0
        self.frameRange = [0,100]
        self.tickRange = [0,100]
        self.stepsPerFrame = 2
        self.ticksPerFrame = 5      
        self.exposureTime = 160 ## ms

        self.maxDelta = [0,0,0]

        self.gcode = []

        self.preset = {'invert':[True,False,True,False,False],
                       'curve':['Point_camera \\ Transform \\ Rotation \\ X Rotation',
                                'Point_camera \\ Transform \\ Rotation \\ Y Rotation',
                                'Point_camera \\ Transform \\ Rotation \\ Z Rotation',
                                'Point_focus \\ Transform \\ Position \\ X Position \\ Float Limit \\ Limited Controller: Bezier Float',
                                'Point_camera \\ Transform \\ Position \\ X Position \\ Limited Controller: Bezier Float'  ]    }

        #self.settingsHandler = self.parent().settingsHandler
        

        self.axisCombos = [ self.ui.comboBox_xAxis, self.ui.comboBox_yAxis, self.ui.comboBox_zAxis, self.ui.comboBox_aAxis, self.ui.comboBox_bAxis ]        
        self.maxDeltaLabels = [self.ui.label_maxXrot, self.ui.label_maxYrot, self.ui.label_maxZrot, self.ui.label_maxArot, self.ui.label_maxBrot ]
                              
        self.maxSpeedLabels = [ [self.ui.label_maxXspeed_min, self.ui.label_maxYspeed_min, self.ui.label_maxZspeed_min, self.ui.label_maxAspeed_min, self.ui.label_maxBspeed_min ],
                                [self.ui.label_maxXspeed_sec, self.ui.label_maxYspeed_sec, self.ui.label_maxZspeed_sec, self.ui.label_maxAspeed_sec, self.ui.label_maxBspeed_sec ]]        


        self.revCheckboxes = QtWidgets.QButtonGroup()
        self.revCheckboxes.setExclusive(False)
        for i, check in enumerate([ self.ui.checkBox_Xrev, self.ui.checkBox_Yrev, self.ui.checkBox_Zrev, self.ui.checkBox_Arev, self.ui.checkBox_Brev ]):
            self.revCheckboxes.addButton(check, i)
            check.setChecked(self.preset['invert'][i])
            

        self.ui.groupBox_xafFile.setEnabled(False)

        self.connectSignals()
        
        self.ui.slider_exposure.setValue(27)


        #self.loadXafFile( 'E:/Projects/MoCo/shots/anim_test_v002/anim_test_v002.xaf' )
        
        
        


    ## -------------------------------------------------------------------------------------
    ## signals

    def connectSignals( self ):
        self.ui.pushButton_loadXaf.clicked.connect( self.openFileDialog )
        self.ui.lineEdit_XafFile.returnPressed.connect( self.openFileFromLineEdit )
        self.ui.spinBox_ticksPerFrame.valueChanged.connect( self.updateFrameRange )

        self.ui.slider_exposure.valueChanged.connect( self.updateExposure )
        self.ui.pushButton_generateGcode.clicked.connect( self.updateGcode )

        self.revCheckboxes.idToggled.connect( self._invertCurve )
        
        for combo in self.axisCombos:
            combo.currentIndexChanged.connect( self.updateCurves )




    ## -------------------------------------------------------------------------------------
    ## File handling

    def openFileDialog( self ):   
        path = QtWidgets.QFileDialog.getOpenFileName( self, 'Open curve file', self.SHOT_FOLDER, '*.xaf' )
        self.loadXafFile(path[0])
    
    def openFileFromLineEdit( self ):
        filepath = self.ui.lineEdit_XafFile.text()
        self.loadXafFile(filepath)

    def loadXafFile( self, path ):
        self.ui.lineEdit_XafFile.setText(path)        

        ## parse/sort the Xaf file into keys/controllers
        self.XafFile = XafFile.ParseXAF(path)
        self.XafFileCurves = XafFile.keysToCurves(self.XafFile)
        
        self.initComboBoxes()
        #self.ui.curveViewWidget.buildCurves(self.XafFileCurves, ["X Axis", "Y Axis", "Z Axis"])

        
        self.ui.spinBox_ticksPerFrame.setValue( self.XafFile['sceneInfo']['ticksPerFrame'] )       

        ## enable controls
        self.ui.groupBox_xafFile.setEnabled(True)

        self.updateCurves()
        self.initInvs()


    def updateCurves(self, reframe=True):               
        self.curveView.set_curves(self._getCurves(), reframe)
        self.curvesUpdated.emit()

    ## -------------------------------------------------------------------------------------
    ## gcode functions

    def updateGcode( self ):
        curves = self._getCurves()

        self.gcode = generateGcodeFromCurves( 
                                    curves,
                                    self.exposureTime,
                                    self.ticksPerFrame, 
                                    self.tickRange, 
                                    self.stepsPerFrame,
                                    ["X", "Y", "Z", "A", "B"],
                                    self.window().settingsHandler
                                    )

        self.gcodeGenerated.emit( self.gcode )
        

    def updateGcodeList( self ):
        self.ui.listWidget_gCode.clear()

        for i, line in enumerate(self.gcode):
            lineItem = GcodeListWidgetItem(line)
            self.ui.listWidget_gCode.addItem(lineItem)            


    def getValuesAtTime( self, t, ticks=False):
        data = []
        curves = self._getCurves()

        if not ticks:
            t = t*self.ticksPerFrame

        for curve in curves:
            data.append(curve.evaluate(t))

        return data



    ## -------------------------------------------------------------------------------------
    ## framerange/exposure settings

    def updateFrameRange( self, tpf ):
        self.tickRange = [  self.XafFile['sceneInfo']['startTick'], 
                            self.XafFile['sceneInfo']['endTick']]
        
        self.frameRange = [ int(self.XafFile['sceneInfo']['startTick']/tpf), 
                            int(self.XafFile['sceneInfo']['endTick']/tpf) ]
        
        self.frames = self.frameRange[1] - self.frameRange[0]

        self.ui.label_startTick.setText( str(self.XafFile['sceneInfo']['startTick']) )
        self.ui.label_endTick.setText( str(self.XafFile['sceneInfo']['endTick']) )    
       
        self.ui.label_startFrame.setText( str(self.frameRange[0]) ) 
        self.ui.label_endFrame.setText( str(self.frameRange[1]) )

        self.ticksPerFrame = tpf

        self.curveView.time_scale = 1/tpf

        self.getMaxDelta()

    def initComboBoxes( self ):
        for combo in self.axisCombos:
            combo.clear()        

        for axis, combo in enumerate( self.axisCombos ):
            combo.addItems( self.XafFile['controllers'].keys() )
            combo.setCurrentText( self.preset['curve'][axis] )
            #combo.setCurrentIndex( min(axis, len(self.XafFile['controllers'].keys()))  )            

    def initInvs( self ):
        for button in self.revCheckboxes.buttons():
            tog = button.isChecked()
            axis = self.revCheckboxes.id(button)
            self._invertCurve(axis, tog)
            

    def updateExposure( self, val ):
        exp = getExposure(val)
        self.exposureTime = exp['millis']

        self.ui.label_exp_str.setText( exp['str'] )
        self.ui.label_exp_ms.setText( str(exp['millis'])+" ms" )

        self.getMaxSpeed()


    ## -------------------------------------------------------------------------------------
    ## motion/speed deltas

    def getMaxDelta( self ):
        if len(self.XafFileCurves)>0:
            for i in range(3):
                d = getMaxDelta(    self._getAxisCurve(i), 
                                    int(self.ticksPerFrame/self.stepsPerFrame),
                                    self.tickRange )
                
                self.maxDeltaLabels[i].setText( str(round(d, 1)) )
                self.maxDelta[i] = d

        self.getMaxSpeed()

    def getMaxSpeed( self ):
        for i in range(3):            
            s = getFeedRate(self.maxDelta[i], self.exposureTime )                
            self.maxSpeedLabels[0][i].setText( str(round(s, 1)) )
            self.maxSpeedLabels[1][i].setText( str(round(s/60, 1)) )

    ## -------------------------------------------------------------------------------------
    ## little helpers

    def _invertCurve( self, axis, tog ):
        curve = self._getAxisCurve(axis)
        if curve is not None:
            #print( axis, tog )
            curve.setInvert( tog ) 

        self.curvesUpdated.emit()
        self.updateCurves(reframe=False)

    def _getAxisCurve( self, axis ):
        if len(self.XafFileCurves)>0:
            i = self.axisCombos[axis].currentIndex()
            if i>=0:
                return self.XafFileCurves[ i ] 

        return AnimCurve(name="None")
            
    def _getCurves( self ):
        curves = []
        for axis, combo in enumerate(self.axisCombos):
            curves.append(self._getAxisCurve(axis))

        return curves




if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    myapp = XafWindowWidget()
    myapp.show()
    
    sys.exit(app.exec_())               

