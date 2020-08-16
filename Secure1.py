from pyimagesearch.tempimage import TempImage
from picamera.array import PiRGBArray
from picamera import PiCamera
import argparse
import warnings
import datetime
import imutils
import json
import time
import cv2

import RPi.GPIO as gpio
import picamera
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from email import encoders
from email.mime.image import MIMEImage

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-c", "--conf", required=True,
    help="path to the JSON configuration file")
args = vars(ap.parse_args())

# filter warnings, load the configuration and initialize the Dropbox
# client
warnings.filterwarnings("ignore")
conf = json.load(open(args["conf"]))
client = None
        
# initialize the camera and grab a reference to the raw camera capture
camera = PiCamera()
camera.resolution = tuple(conf["resolution"])
camera.framerate = conf["fps"]
rawCapture = PiRGBArray(camera, size=tuple(conf["resolution"]))
camera.brightness=55
 
fromaddr = "bagalkotiprateek@gmail.com"    # change the email address accordingly
toaddr = "bagalkotiprateek@gmail.com"
 
mail = MIMEMultipart()
 
mail['From'] = fromaddr
mail['To'] = toaddr
mail['Subject'] = "Attachment"
body = "Please find the attachment"

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

pir=18
HIGH=1
LOW=0
gpio.setwarnings(False)
gpio.setmode(gpio.BCM)            
gpio.setup(pir, gpio.IN)            # initialize GPIO Pin as input
data=""

def sendMail(data):
    mail.attach(MIMEText(body, 'plain'))
    print (data)
    dat='%s.jpg'%data
    print (dat)
    attachment = open(dat, 'rb')
    image=MIMEImage(attachment.read())
    attachment.close()
    mail.attach(image)
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(fromaddr, "mh09bm9586")
    text = mail.as_string()
    server.sendmail(fromaddr, toaddr, text)
    server.quit()

def detect_people():
    # allow the camera to warmup, then initialize the average frame, last
    # uploaded timestamp, and frame motion counter
    print("[INFO] warming up...")
    time.sleep(conf["camera_warmup_time"])
    avg = None
    lastUploaded = datetime.datetime.now()
    motionCounter = 0

    # capture frames from the camera
    for f in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
        # grab the raw NumPy array representing the image and initialize
        # the timestamp and occupied/unoccupied text
        frame = f.array
        timestamp = datetime.datetime.now()
        text = "Unoccupied"

     # resize the frame
        frame = imutils.resize(frame, width=500)
        orig = frame.copy()

        # detect people in the image
        (rects, weights) = hog.detectMultiScale(frame, winStride=(4, 4),
            padding=(8, 8), scale=1.05)

        # convert image to grayscale and blur it
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        # if the average frame is None, initialize it
        if avg is None:
            print("[INFO] starting background model...")
            avg = gray.copy().astype("float")
            rawCapture.truncate(0)
            continue

        # accumulate the weighted average between the current frame and
        # previous frames, then compute the difference between the current
        # frame and running average
        cv2.accumulateWeighted(gray, avg, 0.5)
        frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))

        # threshold the delta image, dilate the thresholded image to fill
        # in holes, then find contours on thresholded image
        thresh = cv2.threshold(frameDelta, conf["delta_thresh"], 255,
            cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)

        # loop over the contours
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < conf["min_area"]:
                continue

            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            text = "Occupied"

        # draw the text and timestamp on the frame
        ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
        cv2.putText(frame, "Room Status: {}".format(text), (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
            0.35, (0, 0, 255), 1)

        # check to see if the frames should be displayed to screen
        if conf["show_video"]:
            # display the security feed
            cv2.imshow("Security Feed", frame)
            key = cv2.waitKey(1) & 0xFF

            # if the `q` key is pressed, break from the lop
            if key == ord("q"):
                break
    
        # clear the stream in preparation for the next frame
        rawCapture.truncate(0)

        
        # check to see if the room is occupied
        if text == "Occupied":
            data= time.strftime("%d_%b_%Y|%H:%M:%S")
            print (data)
            camera.capture('%s.jpg'%data)
            print ("Sending messege")
            sendMail(data)
            print ("Messege Sent")
            # check to see if enough time has passed between uploads
            if (timestamp - lastUploaded).seconds >= conf["min_upload_seconds"]:
                # increment the motion counter
                motionCounter += 1

                # check to see if the number of frames with consistent motion is
                # high enough
                if motionCounter >= conf["min_motion_frames"]:
                    # check to see if dropbox sohuld be used
                    if conf["use_dropbox"]:
                        # write the image to temporary file
                        t = TempImage()
                        cv2.imwrite(t.path, frame)

                        # upload the image to Dropbox and cleanup the tempory image
                        print("[UPLOAD] {}".format(ts))
                        path = "/{base_path}/{timestamp}.jpg".format(
                            base_path=conf["dropbox_base_path"], timestamp=ts)
                        client.files_upload(open(t.path, "rb").read(), path)
                        t.cleanup()

                    # update the last uploaded timestamp and reset the motion
                    # counter
                    lastUploaded = timestamp
                    motionCounter = 0
                print ("End")
                camera.close()
                cv2.destroyAllWindows() 

        # otherwise, House is safe. No introdure detected
        else:
            motionCounter = 0

        
# In[7]:
while 1:
    if gpio.input(pir)==1:
        detect_people()
        while(gpio.input(pir)==1):
            time.sleep(1)
        
    else:
        time.sleep(0.01)