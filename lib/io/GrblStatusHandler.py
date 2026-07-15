from PyQt5.QtCore import QObject, pyqtSignal

from lib.utils.GrblSerial import parseGrblStatus


class GrblStatusHandler( QObject ):
    mposUpdated   = pyqtSignal( list )
    wcoUpdated    = pyqtSignal( list )
    mainUpdated   = pyqtSignal( list )
    axesUpdated   = pyqtSignal( str )
    lineUpdated   = pyqtSignal( int )
    statusUpdated = pyqtSignal( str )

    mpos = []
    wco = []
    main = []
    axes = None
    line = None
    lastStatus = None

    def __init__( self, parent=None ):
        super().__init__(parent)

    def setMpos( self, mpos ):
        self.mpos = mpos
        self.mposUpdated.emit( mpos )
    
    def setWco( self, wco ):
        self.wco = wco
        self.wcoUpdated.emit( wco )

    def setMain( self ):
        main = []
        if len(self.mpos) > 0:
            for axis, val in enumerate(self.mpos):
                v = val
                if len(self.wco) > axis:
                    v -= self.wco[axis]
                
                main.append(v)

        self.main = main
        self.mainUpdated.emit(main)




    def setAxes( self, axes ):
        self.axes = axes
        self.axesUpdated.emit(axes)

    def setLine( self, line ):
        self.line = line
        self.lineUpdated.emit(line)

    def setStatus( self, status ):
        updateMain = False
        self.lastStatus = status.text
        self.statusUpdated.emit( self.lastStatus )

        data = parseGrblStatus( status.text )

        if 'WCO' in data:            
            self.setWco( data['WCO'])
            updateMain = True

        if 'MPos' in data:            
            self.setMpos( data['MPos'] )            
            updateMain = True

        if 'Ln' in data:
            self.setLine( data['Ln'][0] )

        if updateMain:
            self.setMain()



        

