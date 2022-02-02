#author: sabbi
#11/10/2021

import ctypes
import numpy as np
import os
import cv2
import threading


os.environ["GENICAM_ROOT_V2_4"] = "/opt/pleora/ebus_sdk/x86_64/lib/genicam/"	#declaration needed for Linux SDK

lock = threading.Lock()

def calcParam(v,c,n):
	return (((c)<<24)+((v)<<16)+(n))

#check picam.h for parameter definitions
paramFrames = ctypes.c_int(calcParam(6,2,40))	#PicamParameter_ReadoutCount
paramStride = ctypes.c_int(calcParam(1,1,45))	#PicamParameter_ReadoutStride
paramROIs = ctypes.c_int(calcParam(5, 4, 37))	#PicamParameter_Rois
paramReadRate=ctypes.c_int(calcParam(2,1,50))	#PicamParameter_ReadoutRateCalculation
paramExpose=ctypes.c_int(calcParam(2,2,23))		#PicamParameter_ExposureTime

#opencv related functions
def WindowSize(numRows,numCols):
	aspect = 1
	if numRows > 1080:
		aspect = int(numRows/1080)
	elif numCols > 1920:
		aspect = int(numCols/1920)
	winWidth = int(numCols/aspect)
	winHeight = int(numRows/aspect)
	return winWidth, winHeight

def SetupDisplay(numRows,numCols,windowName):        
	if numRows > 1:
		cv2.namedWindow(windowName,cv2.WINDOW_NORMAL)
		winWidth, winHeight = WindowSize(numRows, numCols)
		cv2.resizeWindow(windowName,winWidth,winHeight)

def DisplayImage(imData, windowName):		#data needs to be passed in correct shape
	normData = cv2.normalize(imData,None,alpha=0, beta=65535, norm_type=cv2.NORM_MINMAX)
	cv2.imshow(windowName, normData)
	cv2.waitKey(50)	#cap opencv refresh at 20fps for stability. May be able to keep up faster on higher powered machines. Increase if stability issues.

class camIDStruct(ctypes.Structure):
	_fields_=[
		('model', ctypes.c_int),
		('computer_interface', ctypes.c_int),
		('sensor_name', ctypes.c_char * 64),
		('serial_number', ctypes.c_char * 64)]

class availableData(ctypes.Structure):
	_fields_=[
		('initial_readout', ctypes.c_void_p),
		('readout_count', ctypes.c_longlong)]

class acqStatus(ctypes.Structure):
        _fields_=[
            ('running', ctypes.c_bool),
            ('errors', ctypes.c_int),
            ('readout_rate',ctypes.c_double)]

class acqBuf(ctypes.Structure):
        _fields_=[
            ('memory', ctypes.c_void_p),
            ('memory_size',ctypes.c_longlong)]

class roiStruct(ctypes.Structure):
	_fields_=[
		('x', ctypes.c_int),
		('width', ctypes.c_int),
		('x_binning', ctypes.c_int),
		('y', ctypes.c_int),
		('height', ctypes.c_int),
		('y_binning', ctypes.c_int)]

class roisStruct(ctypes.Structure):
	_fields_=[
		('roi_array', ctypes.c_void_p),
		('roi_count', ctypes.c_int)]


class Camera():
	def __init__(self,*,libPath: str='/usr/local/lib/libpicam.so'):	#class will instantiate and initialize PICam
		self.cam = ctypes.c_void_p(0)
		self.dev = ctypes.c_void_p(0)
		self.camID = camIDStruct(0,0,b'',b'')
		self.numRows = ctypes.c_int(0)
		self.numCols = ctypes.c_int(0)
		self.readRate = ctypes.c_double(0)
		self.picamLib = ctypes.cdll.LoadLibrary(libPath)
		self.counter = 0
		self.totalData = np.array([])
		self.newestFrame = np.array([])
		self.rStride = ctypes.c_int(0)
		self.display = False
		self.runningStatus = ctypes.c_bool(False)
		self.windowName = ''
		self.circBuff = circBuff = ctypes.ARRAY(ctypes.c_ubyte,0)()
		self.aBuf = acqBuf(0,0)
		self.Initialize()

	def AcquisitionUpdated(self, device, available, status):    #PICam will launch callback in another thread
		with lock:
			if status.contents.running:
				self.ProcessData(available.contents, self.rStride.value, saveAll = False)					
			self.runningStatus = status.contents.running
		return 0
        
	def ResetCount(self):
		self.counter = 0
		self.totalData = np.array([])

	def GetReadRate(self):
		self.picamLib.Picam_GetParameterFloatingPointValue(self.cam,paramReadRate,ctypes.byref(self.readRate))

	def Initialize(self):
		initCheck = ctypes.c_bool(0)
		self.picamLib.Picam_InitializeLibrary()
		self.picamLib.Picam_IsLibraryInitialized(ctypes.byref(initCheck))
		print('PICam Initialized: %r'%initCheck.value)

	def Uninitialize(self):
		self.picamLib.Picam_UninitializeLibrary()

	def GetFirstROI(self):		#working with single ROI for basic demonstration
		rois = ctypes.c_void_p(0)		
		self.picamLib.Picam_GetParameterRoisValue(self.cam, paramROIs, ctypes.byref(rois))
		roisCast = ctypes.cast(rois,ctypes.POINTER(roisStruct))[0]
		roiCast = ctypes.cast(roisCast.roi_array,ctypes.POINTER(roiStruct))[0]	#take first ROI
		self.numCols = int(roiCast.width/roiCast.x_binning)
		self.numRows = int(roiCast.height/roiCast.y_binning)
		self.picamLib.Picam_DestroyRois(rois)
		if self.numRows > 1:
			self.display = True		#change this back to True for opencv display

	def Commit(self,*,printMessage: bool=True):
		paramArray = ctypes.pointer(ctypes.c_int(0))
		failedCount = ctypes.c_int(1)
		self.picamLib.Picam_CommitParameters(self.cam, ctypes.byref(paramArray), ctypes.byref(failedCount))
		if failedCount.value > 0:
			print('Failed to commit %d parameters. Cannot acquire.'%(failedCount.value))
			return False
		else:
			self.GetReadRate()
			if printMessage:
				print('\tCommit successful! Current readout rate: %0.2f readouts/sec'%(self.readRate.value))
			return True

	def OpenFirstCamera(self,*,model: int=57): #if a connected camera is found, opens the first one, otherwise opens a demo		
		if self.picamLib.Picam_OpenFirstCamera(ctypes.byref(self.cam)) > 0: #try opening live cam
			self.picamLib.Picam_ConnectDemoCamera(model,b'SLTest',ctypes.byref(self.camID))
			if self.picamLib.Picam_OpenCamera(ctypes.byref(self.camID),ctypes.byref(self.cam)) > 0:
				print('No camera could be opened. Uninitializing.')
				self.Uninitialize()
			else:
				self.picamLib.Picam_GetCameraID(self.cam,ctypes.byref(self.camID))
		else:
			self.picamLib.Picam_GetCameraID(self.cam,ctypes.byref(self.camID))
		print('Camera Sensor: %s, Serial #: %s'%(self.camID.sensor_name.decode('utf-8'),self.camID.serial_number.decode('utf-8')))
		self.GetFirstROI()
		print('\tFirst ROI: %d (cols) x %d (rows)'%(self.numCols,self.numRows))
		self.windowName = 'Readout from %s'%(self.camID.sensor_name.decode('utf-8'))

	def SetExposure(self, time):
		expTime = ctypes.c_double(0)
		expTime.value = time
		self.picamLib.Picam_SetParameterFloatingPointValue(self.cam,paramExpose,expTime)
		print('Trying to commit exposure time to %0.2f ms...'%(expTime.value),end='')
		self.Commit(printMessage=True)

	def ProcessData(self, data, readStride,*,saveAll: bool=True):
		x=ctypes.cast(data.initial_readout,ctypes.POINTER(ctypes.c_uint16))
		for i in range(0,data.readout_count):	#readout by readout
			offset = int((i * readStride) / 2)
			readoutDat = np.asarray(x[offset:int(self.numCols*self.numRows + offset)],dtype=np.uint16)
			readoutDat = np.reshape(readoutDat, (self.numRows, self.numCols))
			if saveAll:
				self.totalData[(self.counter),:,:] = readoutDat
			self.counter += 1
			if i == data.readout_count-1:	#return most recent readout (normalized) to use for displaying
				self.newestFrame = readoutDat

	def AcquireHelper(self):
		dat = availableData(0,0)
		aStatus=acqStatus(False,0,0)
		self.picamLib.Picam_StartAcquisition(self.cam)
		print('Acquisition Started, %0.2f readouts/sec...'%self.readRate.value)
		#start a do-while
		self.picamLib.Picam_WaitForAcquisitionUpdate(self.cam,-1,ctypes.byref(dat),ctypes.byref(aStatus))
		self.ProcessData(dat, self.rStride.value)
		#while part
		while(aStatus.running):
			self.picamLib.Picam_WaitForAcquisitionUpdate(self.cam,-1,ctypes.byref(dat),ctypes.byref(aStatus))
			self.runningStatus = aStatus.running
			if dat.readout_count > 0:					
				self.ProcessData(dat, self.rStride.value)
		#print('...Acquisiton Finished, %d readouts processed.'%(self.counter)) #is not needed since the DisplayCameraData function prints as well

	def Acquire(self,*,frames: int=1):	#will launch the AcquireHelper function in a new thread when user calls it
		frameCount = ctypes.c_int(0)
		frameCount.value = frames
		self.picamLib.Picam_SetParameterLargeIntegerValue(self.cam,paramFrames,frameCount)
		if self.Commit():
			self.ResetCount()
			self.totalData = np.zeros((frameCount.value,self.numRows,self.numCols))
			if self.display:
				SetupDisplay(self.numRows, self.numCols, self.windowName)
			self.picamLib.Picam_GetParameterIntegerValue(self.cam, paramStride, ctypes.byref(self.rStride))			
			acqThread = threading.Thread(target=self.AcquireHelper)
			acqThread.start()	#data processing will be in a different thread than the display

	def DisplayCameraData(self):	#this will block and then unregister callback (if applicable) when done
		#do-while
		cv2.waitKey(100)
		runStatus = ctypes.c_bool(False)
		self.picamLib.Picam_IsAcquisitionRunning(self.cam, ctypes.byref(runStatus))
		self.runningStatus = runStatus
		while self.runningStatus:
			if self.display and len(self.newestFrame) > 0:									
				DisplayImage(self.newestFrame, self.windowName)
		print('Acquisition stopped. %d readouts obtained.'%(self.counter))
		try:
			self.picamLib.PicamAdvanced_UnregisterForAcquisitionUpdated(self.dev, self.acqCallback)
		except:
			pass
		cv2.waitKey(20000)
		cv2.destroyAllWindows()

    
	def AcquireCB(self,*,frames: int=5):	#utilizes Advanced API to demonstrate callbacks, returns immediately
		if self.display:
			SetupDisplay(self.numRows, self.numCols, self.windowName)
		self.ResetCount()
		self.picamLib.Picam_GetParameterIntegerValue(self.cam, paramStride, ctypes.byref(self.rStride))		
		self.picamLib.PicamAdvanced_GetCameraDevice(self.cam, ctypes.byref(self.dev))
		frameCount = ctypes.c_int(0)
		frameCount.value = frames
		self.picamLib.Picam_SetParameterLargeIntegerValue(self.dev,paramFrames,frameCount)	#setting with dev handle commits to physical device if successful
		#circ buffer so we can run for a long time without needing to allocate memory for all of it
		#the buffer array and the data structure should be global or class properties so they remain in scope when the
		#function returns		
		widthNominal = np.floor(512*1024*1024/self.rStride.value)
		if widthNominal < 4:					#if 512MB not enough for 4 frames, allocate for 4 frames
			buffWidth = self.rStride.value*4
		else:
			buffWidth = int(widthNominal)*self.rStride.value
		self.circBuff = ctypes.ARRAY(ctypes.c_ubyte,buffWidth)()
		self.aBuf.memory = ctypes.addressof(self.circBuff)
		self.aBuf.memory_size = ctypes.c_longlong(buffWidth)
		self.picamLib.PicamAdvanced_SetAcquisitionBuffer(self.dev, ctypes.byref(self.aBuf))
		
		CMPFUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(availableData), ctypes.POINTER(acqStatus))
		#lines for internal callback		
		self.acqCallback = CMPFUNC(self.AcquisitionUpdated)
		self.picamLib.PicamAdvanced_RegisterForAcquisitionUpdated(self.dev, self.acqCallback)
		self.picamLib.Picam_StartAcquisition(self.dev)		
		print('Acquisition of %d frames asynchronously started'%(frameCount.value))

	def ReturnData(self):
		return self.totalData

	def Close(self):
		self.picamLib.Picam_CloseCamera(self.cam)
		self.picamLib.Picam_DisconnectDemoCamera(ctypes.byref(self.camID))
		self.Uninitialize()
