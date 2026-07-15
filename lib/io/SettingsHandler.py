import os, sys
from dataclasses import dataclass, field
from PyQt5.QtCore import pyqtSignal, QObject



from lib.utils import XafFile
from lib.utils.AnimCurve import AnimCurve, KeyFrame


##@dataclass
class AxisSettings(QObject):
    axisCurve: AnimCurve = None
    useCurve:  bool = False
    rev:       bool = False
    absolute:  bool = False
    unit:      int = 0 #deg, mm, cm

    revSet = pyqtSignal(bool)
    unitSet = pyqtSignal(int)
    absSet = pyqtSignal(bool)
    curveToggled = pyqtSignal(bool)

    def __init__( self, parent=None ):
        super().__init__(parent)

    def setAxisCurve(self, curve):
        self.axisCurve = curve       
        
    def toggleCurve( self, tog ):
        self.useCurve = tog
        self.curveToggled.emit(tog)        

    def setRev( self, rev ):
        self.rev = rev
        self.revSet.emit(rev)        

    def setUnit( self, unit ):
        self.unit = unit        
        self.unitSet.emit(unit)

    def setAbs( self, tog ):
        self.absolute = tog
        self.absSet.emit(tog)
    
    ## -------------------------------------------------------------------------------------
    ## in/out settings handlers
    
    def getOutputValue( self, val ):        
        out = val

        ## convert value from 3dsmax curves to GRBL value
        if self.useCurve:
            tpf = self.axisCurve.ticksPerFrame
            out = self.axisCurve.evaluate(val*tpf)
        
        if self.rev:
            out *= -1

        return out

    
    def getInputValue( self, val ):        
        out = val        

        ## convert value coming from GRBL to 3dsmax value
        if self.useCurve:            
            tpf = self.axisCurve.ticksPerFrame
            try: 
                out = self.axisCurve.evaluate_inverse(val)[0]/tpf
            except:
                out = val
        
        if self.rev:
            out *= -1

        return out
    
    def getRelativeValue( self, input_val, rel_val, input_space=0, rel_space=0, output_space=0 ):
        ## get relative curve value, mixing between difference spaces 

        ## spaces
        ## 0 = motor space
        ## 1 = curve space
        
        if input_space == 0:
            current_motorSpace = input_val
            current_curveSpace = self.getInputValue( input_val )
        elif input_space == 1:
            current_curveSpace = input_val
            current_motorSpace = self.getOutputValue( input_val )

        if rel_space == 0:
            target_motorSpace = current_motorSpace + rel_val
            target_curveSpace = self.getInputValue( target_motorSpace )
        elif rel_space == 1:
            target_curveSpace = current_curveSpace + rel_val
            target_motorSpace = self.getOutputValue( target_curveSpace )
        
        if output_space == 0:
            return target_motorSpace - current_motorSpace
        elif output_space == 1:
            return target_curveSpace - current_curveSpace






class SettingsHandler( QObject ):
    outValuesSet = pyqtSignal( list )
    inValuesSet =  pyqtSignal( list )

    def __init__( self, num=5, parent=None ):
        super().__init__(parent)

        self.axes = []

        for i in range(num):
            self.axes.append(AxisSettings())

    def numAxes( self ):
        return len(self.axes)

    def getAxisOutputValue( self, axis, inValue ):
        return self.axes[axis].getOutputValue( inValue )
    
    def getAxisInputValue( self, axis, outValue ):        
        return self.axes[axis].getInputValue( outValue )
    
    def getOutputValues( self, values ):
        outValues = []
        for axis, value in enumerate(values):
            outValues.append(self.getAxisOutputValue(axis, value))

        return outValues
        
    def getInputValues( self, values ):
        inValues = []
        for axis, value in enumerate(values):
            inValues.append(self.getAxisInputValue(axis, value))

        return inValues