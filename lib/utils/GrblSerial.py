#   <Idle|MPos:0.000,0.000,0.000,0.000,0.000|Bf:100,1023|FS:0,0|Pn:XYZAB>
# $J=G21G91Y10F10000

def generateJogCmd( jogData, settingsHandler=None, statusHandler=None ):
    ## $J=G21G91Y10F10000
    axes = "XYZABCUVW"

    ## start the jog command
    line = "$J=G21"

    if jogData['abs'] == True:
        line += "G90"
    else:
        line += "G91"    
    
    line += "F"
    line += str(jogData["feedrate"])

    ## if sending a single axis
    if type(jogData["axis"]) == int:
        axis = jogData["axis"]

        line += axes[axis]
        val = jogData["amount"]
        if settingsHandler is not None and statusHandler is not None:
            if settingsHandler.axes[axis].useCurve:
                ## using curve
                axisHandler = settingsHandler.axes[axis]

                if jogData['abs'] == True:
                    val = axisHandler.getOutputValue( val )
                else:
                    ## current position in both motor + curve spaces
                    current_motorSpace = statusHandler.mpos[axis]                     

                    val = axisHandler.getRelativeValue( current_motorSpace, val,
                                                    input_space = 0,
                                                    rel_space = 1,
                                                    output_space = 0)
            else:
                val = settingsHandler.getAxisOutputValue( axis, val )
        line += str(val)    


    ## if sending multiple axes
    elif type(jogData["axis"]) == list and type(jogData["amount"]) == list:        
        for i,axis in enumerate(jogData["axis"]):
            val = jogData["amount"][i]
            if settingsHandler is not None:                
                if settingsHandler.axes[axis].useCurve:
                    ## using curve
                    axisHandler = settingsHandler.axes[axis]

                    if jogData['abs'] == True:
                        val = axisHandler.getOutputValue( val )
                    else:
                        ## current position in both motor + curve spaces
                        current_motorSpace = statusHandler.mpos[axis]                     

                        val = axisHandler.getRelativeValue( current_motorSpace, val,
                                                            input_space = 0,
                                                            rel_space = 1,
                                                            output_space = 0)
                else:
                    val = settingsHandler.getAxisOutputValue( axis, val )   
         
            line += axes[axis]+str(val)

    return line

def setAxisCmd( axis, val, settingsHandler=None ):
    axes = "XYZABCUVW"

    ### if just a single set command is sent
    if type(axis) == int:
        if settingsHandler is not None:
            axisHandler = settingsHandler.axes[axis]
            val = axisHandler.getOutputValue( val )

        line = "G92 "+axes[axis]+str(val)

    ### if a list of set commands is sent
    if type(axis) == list and type(val) == list:
        line = "G92 "
        for i,a in enumerate(axis):
            if settingsHandler is not None:
                axisHandler = settingsHandler.axes[axis]
                val[i] = axisHandler.getOutputValue( val[i] )

            line += axes[a]+str(val[i])

    return line

def generateZeroCmd( axis ):
    return setAxisCmd( axis, 0)

def generateHomeCmd( axis=None ):
    axes = "XYZABCUVW"
    line = "$H"

    if axis is not None:
        line+=axes[axis]

    return line

def cameraCmd( tog, queued = False ):
    if queued:
        return "M62 P2" if tog else "M63 P2"
    else:
        return "M64 P2" if tog else "M65 P2"

def resetCmd():
    return "$X"

def holdCmd( tog ):
    return "!" if tog else "~"


def parseGrblStatus( line ):
    # <Idle|MPos:0.000,0.000,0.000,0.000,0.000|Bf:100,1023|FS:0,0|Pn:XYZAB>
    intTypes = ['Bf', 'FS', 'Ln']
    floatTypes = ['MPos', 'WCO', 'WPos']
    strTypes = ['Pn']

    statusData = dict()

    lineData = line.strip("<> ").split("|")

    statusData['status'] = lineData[0]

    for d in lineData[1:]:
        d = d.split(":")
        data = d[1].split(",")

        if d[0] in intTypes:
            data = [int(f) for f in data]

        if d[0] in floatTypes:
            data = [float(f) for f in data]

        if d[0] in strTypes:
            data = str(data)

        statusData[d[0]] = data

    return statusData


def parseGrblStatusData( line ):
    data = dict()

    lineData = line[1:-1].split("|")

    data['status'] = lineData[0]

    for d in lineData:
        if "MPos" in d:
            axisData = d.split(":")[1].split(",")
            axisData = [float(n) for n in axisData]
            data['axisData'] = axisData
        elif "FS" in d:
            feedrate = float(d.split(":")[1].split(",")[0])
            data['feedrate'] = feedrate   
        elif "WCO" in d:
            workOffsets = d.split(":")[1].split(",")
            workOffsets = [float(n) for n in workOffsets]
            data['workOffsets'] = workOffsets     
        elif "Bf" in d:
            buffer = d.split(":")[1].split(",")
            data['buffer'] = [ int(d) for d in buffer]

    return data