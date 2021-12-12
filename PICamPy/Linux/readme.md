picam.py contains the class definition for Camera, which can be instantiated and then controlled via member functions. Functions are basic and designed for demonstration.

picam_opencv.py is a test script to show how the Camera class can be used to quickly open and acquire with a camera.

This example was made with Linux in mind, but if the libPath kwarg in the constructor is entered as the path to Picam.dll in Windows, the code should work in Windows as well.

code was tested with:
- CentOS7 x86_64 (kernel 3.10.0)
- Python 3.8
- numpy 1.21.4
- opencv-python 4.5.4.60
- PICam 5.11.2