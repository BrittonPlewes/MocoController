from PyQt5 import QtWidgets, QtCore, QtGui




class AxisReadoutText( QtWidgets.QGraphicsTextItem ):
    def __init__( self, parent=None ):
        QtWidgets.QGraphicsTextItem.__init__( self, parent )

        self.textBrush = QtGui.QBrush( QtGui.QColor(255,0,255) )

        self.myfont = QtGui.QFont("Bahnschrift", QtGui.QFont.Weight.Bold)
        #self.myfont.setBrush(self.textBrush)
        self.myfont.setPixelSize(20)

        self.setFont(self.myfont)    
        self.setDefaultTextColor( QtGui.QColor(255,255,255))    


        self.height = 10
        self.coords = [0,0]        
        self.alignRight = False
        self.alignBottom = False

    def setArial( self, bold=False, black=False ):
        if bold:
            self.myfont = QtGui.QFont("Arial Bold", QtGui.QFont.Weight.Bold)
        elif black:
            self.myfont = QtGui.QFont("Arial Black")#, QtGui.QFont.Weight.Bold)
        else:
            self.myfont = QtGui.QFont("Arial", QtGui.QFont.Weight.Bold)

        self.setHeight( self.height )

    def setText( self, text ):
        self.setPlainText( text )
        #self.setDefaultTextColor( QtGui.QColor(255,0,255))  

    def setHeight( self, height ):
        self.height = height
        self.myfont.setPixelSize( int(self.height) )
        self.setFont( self.myfont )

    def setAlign( self, right=False, bottom=False ):
        self.alignRight = right
        self.alignBottom = bottom

    def setCoords(self, xpos, ypos ):
        self.coords = [xpos, ypos]

    def setColor( self, c ):
        self.setDefaultTextColor(c)
        return

    def updateXform( self ):
        w, h = 0,0

        if self.alignRight:         
            w = self.boundingRect().width()

        if self.alignBottom:
            h = self.height

        x = self.coords[0] - w
        y = self.coords[1] - h

        self.setPos(x,y)

    def getXbounds( self ):
        scenePos = self.mapRectToScene(self.boundingRect())        
        w = self.boundingRect().width()
        return [scenePos.x(), scenePos.x()+w]



class AxisReadoutNumberGroup( QtWidgets.QGraphicsItemGroup ):
    def __init__( self, parent=None ):
        super().__init__(parent)

        self.height = 10
        self.coords = [0,0]        
        self.lowerPercentage = 0.75
        self.alignRight = False
        self.alignBottom = False

        self.tens = AxisReadoutText()        
        self.dec = AxisReadoutText()

        self.addToGroup(self.tens)
        self.addToGroup(self.dec)

    def setArial( self, bold=False, black=False ):
        self.tens.setArial(bold=bold, black=black)
        self.dec.setArial(bold=bold, black=black)

    def setLowerPercentage( self, perc ):
        self.lowerPercentage = perc
        self.dec.setHeight(self.height*self.lowerPercentage)

        self.updateXform()

    def setColor( self, c ):
        self.tens.setColor(c)
        self.dec.setColor(c)        

    def setAlign( self, right=False, bottom=False ):
        self.alignRight = right
        self.alignBottom = bottom

        self.tens.setAlign( right, bottom )
        self.dec.setAlign( right, bottom )

    def setCoords( self, x, y ):
        self.coords = [x,y]
        self.updateXform()

    def setHeight( self, height ):
        self.height = height
        self.tens.setHeight(height)
        self.dec.setHeight(height*self.lowerPercentage)
        
        self.updateXform()

    def setValue( self, val ):
        val = str(round( float(val), 2 )).split(".")

        if len(val[1]) < 2:
            val[1] += "0"
        
        self.tens.setText(val[0])        
        self.dec.setText("."+val[1])

        self.updateXform()

    def updateXform(self):
        if self.alignRight:
            self.dec.setCoords(self.coords[0], self.coords[1])
            self.dec.updateXform()

            x = self.dec.getXbounds()

            self.tens.setCoords( x[0], self.coords[1] )
            self.tens.updateXform()
        else:
            self.tens.setCoords(self.coords[0], self.coords[1])
            self.tens.updateXform()

            x = self.tens.getXbounds()
            self.dec.setCoords(  x[1], self.coords[1]  )
            self.dec.updateXform()

        


class AxisReadoutGraphicsWidget( QtWidgets.QGraphicsView ):
    def __init__( self, parent=None ):
        QtWidgets.QGraphicsView.__init__( self, parent )
            
        self.setHorizontalScrollBarPolicy( QtCore.Qt.ScrollBarAlwaysOff )
        self.setVerticalScrollBarPolicy( QtCore.Qt.ScrollBarAlwaysOff )       

        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)        
        self.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        self.setRenderHint(QtGui.QPainter.RenderHint.HighQualityAntialiasing)

        self.setMaximumWidth(600)
        self.aspectRatio = 3.5  

        self.values = {
            'mpos':0,
            'wpos':0,
            'target':0,
            'wco':0,
            'abs':False
        }

        self.setScene(QtWidgets.QGraphicsScene(0,0,1050,300))

        ## bg stuff
        bgBrush = QtGui.QBrush( QtGui.QColor(0,0,0) )
        self.scene().setBackgroundBrush(bgBrush)

        ## text items
        self.mainValue = AxisReadoutNumberGroup()
        self.mainValue.setValue(0)
        self.mainValue.setAlign(right=True, bottom=True)
        self.mainValue.setHeight(330)
        self.mainValue.setCoords(1000, 270 )

        self.axisLabel = AxisReadoutText()
        self.axisLabel.setArial(black=True)
        self.axisLabel.setText("X")
        self.axisLabel.setAlign(right=False, bottom=True)
        self.axisLabel.setHeight(150)
        self.axisLabel.setCoords(20, 270 )

        self.unitLabel = AxisReadoutText()
        self.unitLabel.setArial()
        self.unitLabel.setText("deg")
        self.unitLabel.setAlign(right=False, bottom=True)
        self.unitLabel.setHeight(50)
        self.unitLabel.setCoords( 1000, 280 )

        self.targetLabel = AxisReadoutText()
        self.targetLabel.setArial()      
        self.targetLabel.setText("TAR:")
        self.targetLabel.setAlign(right=True, bottom=True)
        self.targetLabel.setHeight(40)
        self.targetLabel.setCoords(130, 55 )

        self.targetValue = AxisReadoutNumberGroup()
        self.targetValue.setValue(0)
        self.targetValue.setArial(bold=True)
        self.targetValue.setAlign(right=False, bottom=True)
        self.targetValue.setHeight(65)
        self.targetValue.setCoords(140, 55 )
        self.targetValue.setLowerPercentage(0.90)

        self.wcoLabel = AxisReadoutText()
        self.wcoLabel.setArial()
        self.wcoLabel.setText("WCO:")
        self.wcoLabel.setAlign(right=True, bottom=True)
        self.wcoLabel.setHeight(40)
        self.wcoLabel.setCoords(130, 120 )     

        self.absLabel = AxisReadoutText()
        self.absLabel.setArial()
        self.absLabel.setText("ABS")
        self.absLabel.setAlign(right=True, bottom=True)
        self.absLabel.setHeight(40)
        self.absLabel.setCoords(120, 120 )
        self.absLabel.setVisible(False)

        self.wcoValue = AxisReadoutNumberGroup()        
        self.wcoValue.setValue(0)
        self.wcoValue.setArial(bold=True)
        self.wcoValue.setAlign(right=False, bottom=True)        
        self.wcoValue.setHeight(65)
        self.wcoValue.setCoords(140, 120 )
        self.wcoValue.setLowerPercentage(0.90)

        self.scene().addItem( self.mainValue )
        self.scene().addItem( self.axisLabel )
        self.scene().addItem( self.unitLabel )
        self.scene().addItem( self.targetValue )
        self.scene().addItem( self.wcoValue )
        self.scene().addItem( self.targetLabel )
        self.scene().addItem( self.wcoLabel )
        self.scene().addItem( self.absLabel )

        self.mainValue.updateXform()
        self.axisLabel.updateXform()
        self.unitLabel.updateXform()
        self.targetLabel.updateXform()
        self.wcoLabel.updateXform()        
        self.targetValue.updateXform()
        self.wcoValue.updateXform()    
        self.absLabel.updateXform()           

    def sizeHint( self ):
        return QtCore.QSize(210,60)

    def resizeEvent( self, event ):
        super().resizeEvent(event)
        
        height = int(self.frameGeometry().width()/self.aspectRatio)

        self.setMinimumHeight( height )
        self.setMaximumHeight( height )

        #self.scene().setSceneRect( 0, 0, self.frameGeometry().width(), self.frameGeometry().height() ) 

        self.fitInView(self.scene().sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def setMposValue( self, val ):        
        self.values['mpos'] = val
        self.updateMposValue()

    def setWposValue( self, val ):
        self.values['wpos'] = val
        self.updateWposValue()

    def updateMposValue(self):
        if not self.values['abs']:
            self.mainValue.setValue( self.values['mpos']-self.values['wco'] )
        else:            
            self.mainValue.setValue( self.values['mpos'] )

        self.mainValue.updateXform()

    def updateWposValue(self):
        self.mainValue.setValue(self.vales['wpos'])
        self.mainValue.updateXform()

    def setTargetValue( self, val ):
        self.values['target'] = val
        self.targetValue.setValue(val)      
        self.targetValue.updateXform()

    def toggleAbs( self, tog ):
        self.wcoLabel.setVisible( 1-tog )
        self.wcoValue.setVisible( 1-tog )
        self.absLabel.setVisible( tog )

        self.values['abs'] = tog

    def setWcoValue( self, val ):
        if not self.values['abs']:
            self.values['wco'] = val
            self.wcoValue.setValue(val)            
            self.wcoValue.updateXform()
        else:
            self.values['wco'] = 0

        self.updateMposValue()

    def setAxis( self, axis ):
        axes =  ['X', 'Y', 'Z', 'A', 'B', 'C', 'U', 'V', 'W']        
        self.axisLabel.setText(axes[axis])
        self.setColor(axis)

    def setUnit( self, unit ):
        units = ["deg", "mm", "cm"]
        self.unitLabel.setText(units[unit])

    def setColor( self, axis ):
        hues = [0, 128, 225, 64, 192, 200]

        c0 = QtGui.QColor()
        c1 = QtGui.QColor()
        c0.setHsv(hues[axis], 200,255)
        c1.setHsv(hues[axis], 255,120)

        #for item in self.items():
        #    item.setColor(c)
        self.mainValue.setColor(c0)
        self.axisLabel.setColor(c1)
        self.unitLabel.setColor(c1)


