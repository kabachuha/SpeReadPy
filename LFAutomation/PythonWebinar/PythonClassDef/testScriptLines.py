'''
author: sliakat
notepad for line by line tests
'''

from LFAutomation import AutoClassNiche as ac

if __name__=="__main__":
    lf = ac()
    lf.NewInstance(expName='PM1')
    data = lf.Capture()
    print(data[1])
    lf.CloseInstance()