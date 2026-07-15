
def frameRangeInTicks( tpf, range ):
    ## prep the list of frames in ticks
    times = []
    t=range[0]
    while t <= range[1]:
        times.append(t)
        t+=tpf

    return times


def generateGcodeFromCurves( curves, exposure, tpf, framerange, steps, axes, settingsHandler=None ):
    gcode = []    
    line_prefix = "G01 " # linear motion
    photo_cmd = ["M62 P2 ", "M63 P2 "] ## drive aux 2 high/low
    times = frameRangeInTicks(int(tpf/steps), framerange) 

    axis_cmd = ""

    ## start file
    ## G93 means inverse feed rate, F will determine time the move takes -> 1/F minutes    
    gcode.append("N00 G93")

    f = 60000/int(exposure)

    ## do the meat of the gcode
    for n, tick in enumerate(times):
        line = ""
        line += "N" + str(n+1).zfill(2) + " "
        line += line_prefix        
        line += "F" + str( int(f) ) + " "

        ## take the photo
        line += photo_cmd[ n%2 ]

        if tick == framerange[1]:
            tick -= 1

        axis_cmd = ""

        for i, axis in enumerate(axes):
            #val = round(curves[i].getValAtTime(tick), 2)*-1
            val = round(curves[i].evaluate(tick), 2) #*-1

            if settingsHandler is not None:
                val = settingsHandler.getAxisOutputValue(i, val)

            ## some picky sanity checks
            if val == -0.0 or val == 0.0:
                val = 0

            axis_cmd += axis + str(val) + " "

        line += axis_cmd        
        line = line.strip()        
        
        gcode.append(line)

    ## add some buffer commands at the end
    '''
    for p in range(40):
        n+=1
        line = ""
        line += "N" + str(n+1).zfill(2) + " "
        line += line_prefix        
        line += "F" + str( int(f) ) + " "
        line += axis_cmd        
        line = line.strip()    

        gcode.append(line)
    '''

    gcode.append("M30")
    ## return the
    return gcode
