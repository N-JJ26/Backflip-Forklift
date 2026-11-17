# import tags & whatnot

import cv2
from pupil_apriltags import Detector
detector = Detector(families="tag36h11")

cap = cv2.VideoCapture(0)
failCount = 0

while True:
    ret, frame = cap.read()

    if ret == False:
       failCount += 1
       if failCount > 30:
           break
       continue 
    failCount = 0


    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tags = detector.detect(gray)

    for tag in tags: 
        print ("Saw tag", tag.tag_id)

        corners = tag.corners.astype(int)
        cv2.polylines(frame, [corners], True, (0,255, 0), 2) 
        cx = int(tag.center[0])
        cy = int(tag.center[1])
        cv2.putText(frame, str(tag.tag_id), (cx,cy), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        


    cv2.imshow("tags", frame)
    if cv2.waitKey(1) == 27:
        failCount +=1
        break
    
    if len(tags)>0:
        print("tags found: ", len(tags))


cap.release()
cv2.destroyAllWindows()