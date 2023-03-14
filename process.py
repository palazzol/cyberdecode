
import argparse
import wave
import sys
#import matplotlib.pyplot as plt
import datetime
import struct

class CyberamicsTapeFile:
    def __init__(self):
        parser = argparse.ArgumentParser(description='Process Cyberamics tape data.')
        parser.add_argument('infile', type=argparse.FileType('rb'), help='Input file to decode')
        parser.add_argument('-o','--outfile', type=argparse.FileType('wb'), default=sys.stdout, help='Output file')
        parser.add_argument('-b','--bitrate', type=float, default=4800.0, help='nominal bitrate (default=4800.0)')
        parser.add_argument('-s','--start', type=int, default=0, help='Start sample number.  Default is 0.')
        parser.add_argument('-e','--end', type=int, default=-1, help='End sample number.  Default is end of file.')
        parser.add_argument('-g','--energy', type=float, default=3.0, help='energy window (default=2.0 bits)')
        #parser.add_argument('-m','--measure', action='store_true', help='measure mode')
        #parser.add_argument('-d','--dcwindow', type=float, default=1.5, help='Window size to remove DC offset and low frequency noise.  Default = 1.5 bits.  Recommended values to be > 1.1 and < 4.5, but avoid number near integers.  Use 0.0 or negative to disable)')
        #parser.add_argument('-f','--highfilter', type=float, default=1.0, help='Simple high frequency filter/attentuator, specified as a decimalized percentage of the signal range that is the max sample-to-sample delta cap.  Only used if value is in the range of (0.0,1.0].  For example, 0.1 means that the sample-to-sample delta would be capped at 10%%.  Default is 1.0 (i.e. 100%% delta is allowed).')
        self.args = parser.parse_args()
        self.numtracks = None
        self.framerate = None
        self.sampwidth = None
        self.nframes = None
        #self.persample = None
        #self.args.outfile.write('cmds')
        #for arg in sys.argv:
        #    self.args.outfile.write(' '+arg)
        #self.args.outfile.write('\n')
        #self.args.outfile.write('args '+str(self.args)+'\n')
        self.sample_buf = []
        self.x_widths = []
        self.y_widths = []

        self.last_x_peak = 0.0
        self.last_y_peak = 0.0
        self.last_symbol = ''
        self.num_consec_S = 0
        self.value = 0
        self.num_bits_found = 0
        self.window_samples = []
        self.carrier_detect = False
        self.last_timestamp = -1

    def processCode(self, value):
        self.outfile.write(struct.pack('i',self.samplenum))
        self.outfile.write(struct.pack('c',bytes([value])))
        if value == 0x00:
            if self.last_timestamp == -1:
                message = "Timestamp       initial"
            else:
                delta_ms = (self.samplenum - self.last_timestamp)*1000.0/self.framerate
                td = datetime.timedelta(milliseconds = delta_ms)
                message = "Timestamp       delta = " + str(td)
            self.last_timestamp = self.samplenum
            return message
        elif (value & 0xf0) == 0x30:
            if value & 0x01:
                enable = "ON"
            else:
                enable = "OFF"
            bank = (value >> 1) & 3
            return f"Command:        BANK:{bank} {enable}"
        elif (value & 0xe0) == 0x40:
            return f"Channel:        {(value&0x1f)}"
        else:
            return f"???             0x{value:02X}"
        
    def processBit(self, bit):
        #print('ProcessBit: ', self.samplenum, bit)
        if self.num_bits_found == 0:
            if bit == 0:  # start bit!
                self.num_bits_found = 1
                self.value = 0
        elif self.num_bits_found == 9:
            if bit != 1:  # stop bit, should be a 1
                self.PrintWithTimeStamp("ERROR")
                self.value = 0
                self.num_bits_found = 0
            else:
                desc = self.processCode(self.value)
                self.PrintWithTimeStamp(f"{str(bytes([self.value])):10} {desc}")
                self.num_bits_found = 0
        else:
            #print("got bit",bit,self.num_bits_found)
            # UART bits are LSB first
            self.value >>= 1
            if bit:
                self.value |= 0x80
            self.num_bits_found += 1

    def processPeak(self,x_peak, y_peak):
        #print(f'processPeak: {self.samplenum}')
        energy_thresh = 100000
        # TBD: We need a better way to calculate energy here
        # Do we have a signal?
        #if self.energy > energy_thresh:
        if abs(y_peak - self.last_y_peak) > energy_thresh:
            # Is this peak within a bit time of the last one?
            if x_peak-self.last_x_peak < self.samples_per_bit*1.2:
                #print(x_peak, y_peak, x_peak-self.last_x_peak, y_peak-self.last_y_peak)
                #print(x_peak, x_peak-self.last_x_peak)
                #if abs(self.last_y_peak) > 30000:
                #if True:
                self.x_widths.append((x_peak-self.last_x_peak)/10.0)
                self.y_widths.append(abs(y_peak-self.last_y_peak)/(pow(2,24)/2))
                # Is it a long interval, or a short one
                if (x_peak-self.last_x_peak) > (self.samples_per_bit*0.75):
                    symbol = 'L'
                    #print(self.samplenum, 'L')
                else:
                    symbol = 'S'
                    #print(self.samplenum, 'S')

                # Crazy decoding logic
                if symbol == 'L' and ((self.last_symbol == 'S') or (self.last_symbol == 'L')):
                    self.processBit(1)
                elif symbol == 'S' and self.last_symbol == 'S' and ((self.num_consec_S % 2) == 1):
                    self.processBit(0)

                # Count consecutive S
                if symbol == 'S':
                    self.num_consec_S += 1
                elif symbol == 'L':
                    self.num_consec_S = 0

                # Save the last symbol
                self.last_symbol = symbol
            else:
                # False alarm, reset symbol stuff
                if self.last_symbol != '':
                    self.PrintWithTimeStamp("<break>")
                    self.last_symbol = ''
        # Save the last x,y peaks
        self.last_x_peak = x_peak
        self.last_y_peak = y_peak

    def processSample(self, sample):
        # This uses max/min "peak" detection, to help with drifting DC offsets

        # First have an energy calculator
        window_size = self.args.energy*self.samples_per_bit
        if len(self.window_samples) >= window_size:
            self.window_samples.pop(0)
        self.window_samples.append(sample)
        if len(self.window_samples) != window_size:
            return
        self.energy = max(self.window_samples) - min(self.window_samples)

        if self.energy < 1000000:
            if self.carrier_detect == True:
                self.carrier_detect = False
                self.PrintWithTimeStamp('END')
                self.last_timestamp = -1
            return
        else:
            if self.carrier_detect == False:
                self.carrier_detect = True
                self.PrintWithTimeStamp('START')

        #print(self.samplenum, self.energy)

        # Fit a parabola to 3 points, try to find a max/min in the interval

        # make sure we have three samples
        self.sample_buf.append(sample)
        if len(self.sample_buf) > 3:
          self.sample_buf = self.sample_buf[1:]
        if len(self.sample_buf) != 3:
            return

        # A*x*x + B*x + C = y
        A = 0.5*( 1.0*self.sample_buf[2] - 2.0*self.sample_buf[1] + 1.0*self.sample_buf[0])
        B = 0.5*(-3.0*self.sample_buf[2] + 4.0*self.sample_buf[1] - 1.0*self.sample_buf[0])
        C = self.sample_buf[2]
        # Straight line has no max/min
        if A == 0.0:
            return
        # max/min at y' = 2*A*x + B = 0
        x_peak = -B/(2*A)
        # Note, y'' = 2*A, the curvature (concave up or down)
        # TBD: We should probably only accept a peak that is a different sign from the last one
        # Is it in the interval?
        if (x_peak >= 0) and (x_peak <= 2):
            y_peak = A*x_peak*x_peak + B*x_peak + C
            self.processPeak(self.samplenum - x_peak, y_peak)

    def processFile(self):
        wr = wave.Wave_read(self.args.infile)
        self.numtracks = wr.getnchannels()
        self.framerate = wr.getframerate()
        self.sampwidth = wr.getsampwidth()
        self.nframes = wr.getnframes()

        if self.numtracks != 2:
            print('Error: wav file must have 2 tracks, but has {numtracks} tracks')
            return -1

        print(f'File Parameters:')
        print(f'Filename:     {self.args.infile.name}')
        print(f'Frame Rate:   {self.framerate}')
        print(f'Sample Width: {self.sampwidth}')
        print(f'Num Frames:   {self.nframes}')

        print(f'Decoder Parameters:')
        print(f'Bit Rate:     {self.args.bitrate}')

        self.samples_per_bit = (self.framerate+0.0) / self.args.bitrate

        # reading track 1 (0 is audio, 1 is data)
        offset = 1*self.sampwidth

        #self.lastsample = 0
        #self.window_samples = []
        #self.lastzero = -1
        #self.receiving_zero = False
        #self.bits_received = 0
        #self.lastbyte = -1

        self.outfile = self.args.outfile

        if self.args.start != 0:
            i = self.args.start 
            frame = wr.readframes(self.args.start)
        else:
            i = 0
        if self.args.end != -1:
            endrange = self.args.end
        else:
            endrange = self.nframes
        for i in range(i, endrange):
            self.samplenum = i
            frame = wr.readframes(1)
            sample = int.from_bytes(frame[offset:offset+self.sampwidth],'little',signed=True)
            self.processSample(sample)
            #print(i, sample)
        #print(self.x_widths)
        #plt.plot(self.x_widths, self.y_widths, '+')
        #plt.show()
        self.outfile.close()
        return 0;

    def PrintWithTimeStamp(self, message):
        time_ms = self.samplenum*1000.0/self.framerate
        td = datetime.timedelta(milliseconds=time_ms)
        print(f"{td} {self.samplenum:,}: {message}")

    # Unused
    """
    def calculateExactZeroOld(self, lastsample, sample, samplenum):
        lastsamplenum = samplenum-1
        exactsamplenum = (sample*lastsamplenum-lastsample*samplenum)/(sample-lastsample)
        return exactsamplenum

    def processSampleOld(self, sample):
        # This uses a conventional zero-crossing detector
        if self.samplenum % 1000000 == 0:
            print(f'Processing sample #{self.samplenum}...')

        window_size = 20
        if len(self.window_samples) >= window_size:
            self.window_samples.pop(0)
        self.window_samples.append(sample)
        if len(self.window_samples) != window_size:
            return

        energy = max(self.window_samples) - min(self.window_samples)

        if energy < 1000000:
            self.char_received = 0
            self.bits_received = 0
        else:
            #if sample == 0:
            #    print(self.samplenum, energy, "Zero Sample!!!")
            #    #sldkfjsdlfkj

            if (self.lastsample < 0 and sample >= 0) or (self.lastsample >= 0 and sample < 0):
                zero = self.calculateExactZero(self.lastsample,sample,self.samplenum)
                if self.lastzero != -1:
                    gap = zero-self.lastzero
                else:
                    gap = 0.0
                #print(self.samplenum, energy, gap, "Zero Crossing")
                self.lastzero = zero
                if gap != 0.0:
                    thresh = 7.5
                    if gap > thresh:
                        if self.receiving_zero == True:
                            print(self.samplenum, '***Error***')
                            self.receiving_zero = False
                        else:
                            #print(self.samplenum, 'outbit: 1')
                            self.receiving_zero = False
                            if self.bits_received == 0:
                                pass
                            elif self.bits_received < 9: # data bits
                                self.char_received <<= 1
                                self.char_received |= 1
                                self.bits_received += 1
                            else:
                                c = self.bitreverse[self.char_received]
                                #print('*', self.lastbyte, self.samplenum, self.samplenum-self.lastbyte)
                                # first time through
                                if self.lastbyte == -1:
                                    self.charlist = b''
                                    self.samplenumlist = []
                                # first byte of new sequence
                                elif (self.samplenum - self.lastbyte) > 120:
                                    print(f'[{self.samplenumlist[0]:9}-{self.samplenumlist[0]:9}]   {self.charlist}', file=self.args.outfile)
                                    self.charlist = b''
                                    self.samplenumlist = []
                                self.samplenumlist.append(self.samplenum)
                                self.charlist += c.to_bytes(1,byteorder="big")
                                self.lastbyte = self.samplenum
                                #print(f'sample: {self.samplenum} outchar: 0x{c:02x} {c.to_bytes(1,byteorder="big")}', file=self.args.outfile)
                                #if self.char_recieved < 0x10:
                                #    print(f'{self.samplenum} outchar: 0x0{hex(self.char_received)}')
                                #else:
                                #    print(f'{self.samplenum} outchar: 0x{hex(self.char_received)}')
                                self.char_received = 0
                                self.bits_received = 0
                    else:
                        if self.receiving_zero == False:
                            self.receiving_zero = True
                        else:
                            #print(self.samplenum, 'outbit: 0')
                            self.receiving_zero = False
                            if self.bits_received == 0:
                                self.char_received = 0   # start bit
                                self.bits_received += 1
                            elif self.bits_received < 9: # data bits
                                self.char_received <<= 1
                                self.bits_received += 1
                            elif self.bits_received > 9:
                                print(self.samplenum, '***Error***')
                                self.bits_received = 0
                                self.char_received = 0

        self.lastsample = sample
        """



if __name__ == '__main__':
    sys.exit(CyberamicsTapeFile().processFile())


