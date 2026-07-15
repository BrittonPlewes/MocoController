
from PyQt5 import QtWidgets, QtCore, uic, QtGui


class GcodeListWidgetItem( QtWidgets.QListWidgetItem ):
    def __init__( self, line, parent=None):
        QtWidgets.QListWidgetItem.__init__( self, parent )

        self.gcodeLine = line
        self.setText( self.gcodeLine )

        self.statusColors = [   [0,0,0],    ## basic
                                [0,255,255],  ## sent
                                [0,255,0]   ## complete
        ]
    
    def setStatus( self, status ):
        c = self.statusColors[status]
        color = QtGui.QColor()
        color.setRgb( c[0], c[1], c[2] )
        self.setForeground( QtGui.QBrush(color) )


class GcodeListWidget( QtWidgets.QListWidget ):
    def __init__( self, parent=None ):
        QtWidgets.QListWidget.__init__( self, parent )

        self.complete = 0
        self.sent = 0

    def setSingleIndexStatus( self, i, status ):
        if self.count() > i:
            self.item(i).setStatus(status)

    def setStatusToRow( self, sent=None, complete=None ):
        #self.complete = complete
        #self.sent = sent

        if complete is not None:
            self.complete = complete

            for i in range(self.complete+1):
                self.setSingleIndexStatus(i, 2)

        if sent is not None:
            self.sent = sent

            for i in range(self.complete+1, self.sent):
                self.setSingleIndexStatus(i, 1)

    def setGcode( self, gcode ):
        self.clear()
        for i, line in enumerate(gcode):
            lineItem = GcodeListWidgetItem(line)
            self.addItem(lineItem)     