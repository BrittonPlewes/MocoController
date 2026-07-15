##  ##  ##  ##  ##  ##  ##  ##  ##  
##  parsing a 3dsmax XAF anim file
##

from lib.utils.AnimCurve import AnimCurve, KeyFrame


def parseKeys( controller ):
    from PyQt5.QtCore import QPointF

    floatkeys = ['v', 'inTanVal', 'outTanVal', 'inLen', 'outLen' ]
    intkeys = ['t']

    finalkeys = None


    if controller.attrib['classOf']	== 'Bezier Float':		
        ## only parse Xaf data if from a bezier float
        ## the xaf files have a lot of redundant stuff

        name = controller.attrib['name']        
        rawkeys = controller.iter('Key')

        keys = []
        finalkeys = []

        #going through the key frames and sorting out the info
        for each in rawkeys:
            info = each.attrib

            for key in floatkeys:
                info[key] = float( info[key] )

            for key in intkeys:
                info[key] = int( info[key] )

            keys.append( info )		

        #sorting through the info	
        count = len(keys)

        for i in range( count ):
            keyinfo = dict()            

            v = keys[i]['v']
            t = keys[i]['t']

            #cleaning up the tangent info
            #cuz the way max stores it is bonkers
            #except if there's only one key, then don't even bother           
            if count>1:
                if i==0:
                    inHspan = 0.0
                    outHspan = keys[i+1]['t'] - keys[i]['t']
                elif i>0 and i<len(keys)-1:
                    inHspan = keys[i]['t'] - keys[i-1]['t']
                    outHspan = keys[i+1]['t'] - keys[i]['t']					
                else:
                    inHspan = keys[i]['t'] - keys[i-1]['t']
                    outHspan = 0.0
            else:
                inHspan=0.0
                outHspan=0.0

            ## the way claude wants to do it
            inTanLen = keys[i]['inLen'] *-1
            inTanVal = keys[i]['inTanVal'] * abs(inHspan) * (abs(inTanLen))

            outTanLen = keys[i]['outLen']
            outTanVal = keys[i]['outTanVal'] * abs(outHspan)*(abs(outTanLen))


            ## convert from radians to degrees
            if "rot" in controller.attrib['filterType']:
                import math
                v = math.degrees(v)
                inTanVal  = math.degrees(inTanVal)
                outTanVal = math.degrees(outTanVal)                
            

            #tan_in = QtCore.QPointF( inTanLen, inTanVal )
            #tan_out = QtCore.QPointF( outTanLen, outTanVal )

            k = KeyFrame(   time=t, 
                            value=v,
                            tangent_in=QPointF( inTanLen, inTanVal ),
                            tangent_out=QPointF( outTanLen, outTanVal ),
                            tangent_mode="free")

            finalkeys.append( k )

    return finalkeys


def keysToCurves(xafFile): #controllers, sceneinfo):
    controllers = xafFile['controllers']
    sceneInfo = xafFile['sceneInfo']

    curves = []

    for name in controllers.keys():
        c = AnimCurve(name=name.split('\\')[-1], keyframes=controllers[name], ticksPerFrame=sceneInfo['ticksPerFrame'])
        curves.append(c)

    return curves    



def ParseXAF( filename ):
    import xml.etree.ElementTree as ET   

    file = ET.parse(filename)
    root = file.getroot()	


    intAttribs = ['startTick', 'endTick', 'frameRate', 'ticksPerFrame']

    data = dict()
    controllers = dict()
    sceneinfo = dict()

    for each in root:
	    ## collect the keyframes
        if each.tag == "Node":
            for c in each.iter('Controller'):		
                keys = parseKeys( c )

                if keys is not None:
                    controllers[c.attrib['name']] = keys

        ## collect the sceneinfo				
        if each.tag == "SceneInfo":
            for attrib in each.keys():				
                info = each.attrib[attrib]
                if attrib in intAttribs:
                    info = int(info)
					
                    sceneinfo[attrib] = info


    data['controllers'] = controllers
    data['sceneInfo']   = sceneinfo
    
    return data