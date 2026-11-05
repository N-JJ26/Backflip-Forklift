import threading

import numpy as np
from imutils.video import VideoStream
import imutils
import cv2;
from pupil_apriltags import Detector
import socket

url = "http://192.168.50.220/stream"

at_detector = Detector(
   families="tag36h11",
   nthreads=1,
   quad_decimate=1.0,
   quad_sigma=0.0,
   refine_edges=1,
   decode_sharpening=0.25,
   debug=0
)

img = cv2.VideoCapture(url)

at_detector.detect(img)

TCP_IP = '192.168.50.220'
TCP_PORT = 5005

url='http://192.168.50.220/stream'
im=None

def socket_setup():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Connect to the ESP32
    print(f"Connecting to ESP32 at {TCP_IP}:{TCP_PORT}...")
    s.connect((TCP_IP, TCP_PORT))
    print("Succesfully connected to ESP32.")

    return s

def video_stream(url):
    #Define a video capture object
    vid = cv2.VideoCapture(url)
    #keep looping
    while True:
        #Grab the current frame stored at the ESP32-CAM
        ret, frame=vid.read()
        if not ret:
            print("Couldn't read frame. Killing thread.")
            break

        # resize frame
        frame = imutils.resize(frame, width=600)

        #Show the frame to the computer screen
        cv2.imshow("Frame", frame)
        cv2.waitKey(1)

if __name__ == "__main__":
    # Connect to the ESP32
    sock = socket_setup()

    # Start up both the video stream and keyboard reader threads
    threading.Thread(target=video_stream, args=(url,), daemon=True).start()
