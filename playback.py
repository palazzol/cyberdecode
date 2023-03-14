
import pyaudio
import argparse
import wave
import sys
import time
import struct
import datetime
from enum import Enum
import kivy
from kivy.graphics import *
from kivy.app import App
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.core.window import Window

class MyWidget(Widget):
    def __init__(self, **kwargs):
        super(MyWidget, self).__init__(**kwargs)
        self.bind(pos=self.update_canvas)
        self.bind(size=self.update_canvas)
        self.add_widget(Label(text="Hello"))
        Window.size = (1280, 720)
        self.update_canvas()
        Clock.schedule_interval(self.update_canvas, 1.0/60)

    def update_canvas(self, *args):
        app = App.get_running_app()
        self.canvas.clear()
        L = 20
        width,height = self.size
        with self.canvas:
            for bank in range(0,16):
                r = 0
                g = 0
                b = 0
                if ((bank+1) & 0x01):
                    r = 1.0
                if ((bank+1) & 0x02):
                    g = 0.5
                    if r == 1.0:
                        g = 1.0
                if ((bank+1) & 0x04):
                    b = 1.0
                Color(r, g, b)
                for channel in range(0,32):
                    if app.leds[bank*32+channel] == 1:
                        index = bank*32+channel
                        if index < 8*32:
                            p = (((index // 8)*2*L+L/2),height - ((index % 8)*2*L+2*L))
                        else:
                            index = index - 8*32
                            p = (((index // 8)*2*L+L/2),height - ((index % 8)*2*L+2*L) - height/2)
                        Ellipse(pos=p, size = (L,L))
                Color(1, 1, 1)
                Line(points=[(0,height/2),(width,height/2)])
                for i in range(0,9):
                    Line(points=[(8*L*i, height), (8*L*i, 0)])

class PlaybackApp(App):
    def __init__(self):
        App.__init__(self)

        parser = argparse.ArgumentParser(description='Process Cyberamics tape data.')
        parser.add_argument('-a','--audiofile', type=argparse.FileType('rb'), help='Input audio file to play')
        parser.add_argument('-c','--cmdfile', type=argparse.FileType('rb'), help='Input command file')
        parser.add_argument('-s','--start', type=int, default=0, help='Start sample number.  Default is 0.')
        parser.add_argument('-e','--end', type=int, default=-1, help='End sample number.  Default is end of file.')
        print(sys.argv)
        args = parser.parse_args(sys.argv[1:])
        self.audfile = args.audiofile
        print(self.audfile)
        self.cmdfile = args.cmdfile
        #self.chunk_size = 1000
        self.last_timestamp = -1
        self.counter_bytes = 0
        self.counter = 0x000000
        self.bank = 0
        self.value = 0
        self.leds = []
        for i in range(0, 16*32):
            self.leds.append(0)
        #self.enable = 0
        #self.bank = 0
        self.DecoderState = Enum('DecoderState', ['IDLE', 'C2X', 'C3A3F', 'C3039', 'C3039_2', 'C2X_2', 'C303F_2'])
        self.decoderstate = self.DecoderState.IDLE

    def UpdateLed(self, bank, channel, enable):
        self.leds[bank*32+channel] = enable

    def ProcessCode2(self, ts, value):
        value = value[0]
        if self.decoderstate == self.DecoderState.IDLE:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                return message
            elif (value & 0xf0) == 0x20:
                self.active_command = value
                self.decoderstate = self.DecoderState.C2X
                return f'Got {value:02x}'
            elif (value & 0xf0) == 0x30:
                self.active_command = value
                if value & 0x0f < 10:
                    self.decoderstate = self.DecoderState.C3039
                else:
                    self.decoderstate = self.DecoderState.C3A3F
                return f'Got {value:02x}'
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C2X:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                self.decoderstate = self.DecoderState.IDLE
                return message
            elif self.active_command == 0x24:
                s = f'Track Tag Byte: {chr(value)}'
                self.decoderstate = self.DecoderState.C2X_2
                return s
            elif (value & 0xe0) == 0x40:
                channel = value & 0x1f
                bank = ((self.active_command & 0x0e) >> 1) + 8
                enable = self.active_command & 0x01
                s = f"Channel:        BANK:{bank} {enable} {channel}"
                self.UpdateLed(bank, channel, enable)
                self.decoderstate = self.DecoderState.C2X_2
                return s
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C2X_2:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                self.decoderstate = self.DecoderState.IDLE
                return message
            elif self.active_command == 0x24:
                s = f'Track Tag Byte: {chr(value)}'
                return s
            elif (value & 0xf0) == 0x20:
                self.active_command = value
                self.decoderstate = self.DecoderState.C2X
                return f'Got {value:02x}'
            elif (value & 0xf0) == 0x30:
                self.active_command = value
                if value & 0x0f < 10:
                    self.decoderstate = self.DecoderState.C3039
                else:
                    self.decoderstate = self.DecoderState.C3A3F
                return f'Got {value:02x}'
            elif (value & 0xe0) == 0x40:
                channel = value & 0x1f
                bank = ((self.active_command & 0x0e) >> 1) + 8
                enable = self.active_command & 0x01
                s = f"Channel:        BANK:{bank} {enable} {channel}"
                self.UpdateLed(bank, channel, enable)
                return s
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C3039:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                #self.decoderstate = self.DecoderState.IDLE
                return message
            elif (value & 0xf0) == 0x30:
                if value & 0x0f < 10:
                    self.decoderstate = self.DecoderState.C3039_2
                    self.lap = int(self.active_command & 0x0f)
                    self.lap *= 10
                    self.lap += int(value & 0x0f)
                    self.decoderstate = self.DecoderState.C3039_2
                    return f'Got {value:02x}'
                else:
                    self.lap = 0
            elif (value & 0xe0) == 0x40:
                channel = value & 0x1f
                bank = (self.active_command & 0x0e) >> 1
                enable = self.active_command & 0x01
                s = f"Channel:        BANK:{bank} {enable} {channel}"
                self.UpdateLed(bank, channel, enable)
                self.decoderstate = self.DecoderState.C303F_2
                return s
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C3039_2:
            if (value & 0xf0) == 0x30:
                if value & 0x0f < 10:
                    self.lap *= 10
                    self.lap += int(value & 0x0f)
                    s = f'Lap Counter: {self.lap:03}'
                    self.lap = 0
                    self.decoderstate = self.DecoderState.IDLE
                    return s
                else:
                    self.lap = 0
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C3A3F:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                #self.decoderstate = self.DecoderState.IDLE
                return message
            elif (value & 0xe0) == 0x40:
                channel = value & 0x1f
                bank = (self.active_command & 0x0e) >> 1
                enable = self.active_command & 0x01
                s = f"Channel:        BANK:{bank} {enable} {channel}"
                self.UpdateLed(bank, channel, enable)
                self.decoderstate = self.DecoderState.C303F_2
                return s
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s
        elif self.decoderstate == self.DecoderState.C303F_2:
            if value == 0x00:
                if self.last_timestamp == -1:
                    message = "Timestamp       initial"
                else:
                    delta_ms = (ts - self.last_timestamp) * 1000.0 / 48000.0
                    td = datetime.timedelta(milliseconds=delta_ms)
                    message = "Timestamp       delta = " + str(td)
                self.last_timestamp = self.samplenum
                self.decoderstate = self.DecoderState.IDLE
                return message
            elif (value & 0xf0) == 0x20:
                self.active_command = value
                self.decoderstate = self.DecoderState.C2X
                return f'Got {value:02x}'
            elif (value & 0xf0) == 0x30:
                self.active_command = value
                if value & 0x0f < 10:
                    self.decoderstate = self.DecoderState.C3039
                else:
                    self.decoderstate = self.DecoderState.C3A3F
                return f'Got {value:02x}'
            elif (value & 0xe0) == 0x40:
                channel = value & 0x1f
                bank = (self.active_command & 0x0e) >> 1
                enable = self.active_command & 0x01
                s = f"Channel:        BANK:{bank} {enable} {channel}"
                self.UpdateLed(bank, channel, enable)
                return s
            else:
                s = f'Error - Got {value:02x} in {self.decoderstate}'
                self.decoderstate = self.DecoderState.IDLE
                return s

    def ProcessCode(self, ts, value):
        value = value[0]
        if self.counter_bytes > 0:
            self.counter <<= 8
            self.counter += value
            self.counter_bytes += 1
            s = f"Lap:            0x{value:02X}"
            if self.counter_bytes == 3:
                lap = ((self.counter & 0x0F0000) >> 16)*100 + \
                      ((self.counter & 0x000F00) >> 8) * 10 + \
                       (self.counter & 0x00000F)
                self.counter_bytes = 0
                s += '\n' + f"Lap Counter: {lap:03d}"
            return s
        if value == 0x00:
            self.counter = 0
            self.counter_bytes = 0
            if self.last_timestamp == -1:
                message = "Timestamp       initial"
            else:
                delta_ms = (ts - self.last_timestamp)*1000.0/48000.0
                td = datetime.timedelta(milliseconds = delta_ms)
                message = "Timestamp       delta = " + str(td)
            self.last_timestamp = self.samplenum
            return message
        elif (value & 0xf0) == 0x30:
            digit = value & 0x0f
            if digit < 10:
                self.counter = value
                self.counter_bytes += 1
                if self.counter_bytes == 3:
                    lap = ((self.counter & 0x0F0000) >> 16) * 100 + \
                          ((self.counter & 0x000F00) >> 8) * 10 + \
                          (self.counter & 0x00000F)
                    self.counter = 0
                    self.counter_bytes = 0
                    return f"Lap Counter: {lap:03d}"
            else:
                self.counter = 0
                self.counter_bytes = 0
            bank = ((value >> 1) & 7)
            self.bank = bank
            self.enable = value&0x01
            return f"Command:        0x{value:02X}"
        elif (value & 0xe0) == 0x40:
            self.counter = 0
            self.counter_bytes = 0
            self.channel = value&0x1f
            self.leds[self.bank * 32 + self.channel] = self.enable & 0x01
            if self.enable & 0x01:
                enable = "ON "
            else:
                enable = "OFF"
            return f"Channel:        BANK:{self.bank} {enable} {self.channel}"
        else:
            self.counter = 0
            self.counter_bytes = 0
            return f"???             0x{value:02X}"

    def Callback(self, in_data, frame_count, time_info, status):
        # Read stream data, filter audio channel only
        data = self.wf.readframes(frame_count)
        data2 = b''
        for i in range(0,frame_count):
            data2 += data[i*6:i*6+3]
        self.samplenum += frame_count

        # Process codes as needed here
        while True:
            if self.timestamps[self.codeindex] < self.samplenum:
                msg = self.ProcessCode2(self.timestamps[self.codeindex],self.codes[self.codeindex])
                if msg.startswith('Error'):
                    print(msg)
                elif msg.startswith('Track'):
                    print(msg)
                elif msg.startswith('Lap'):
                    print(msg)
                self.codeindex += 1
            else:
                break

        return (data2, pyaudio.paContinue)

    def build(self):
        self.w = MyWidget()
        self.w.add_widget(Label(text="Hello World"))
        return self.w

    def Run(self):
        # Create Window
        # TBD

        # Read codes into buffer
        self.timestamps = []
        self.codes = []
        struct_fmt = 'is'
        struct_len = struct.calcsize(struct_fmt)
        struct_unpack = struct.Struct(struct_fmt).unpack_from
        num_codes = 0
        while True:
            d = self.cmdfile.read(struct_len)
            if not d: break
            s = struct_unpack(d)
            self.timestamps.append(s[0])
            self.codes.append(s[1])
            num_codes += 1
        print(f'Read {num_codes} codes.')
        self.codeindex = 0

        # Read Wave File Header
        self.wf = wave.open(self.audfile, 'rb')
        self.samplenum = 0
        self.wf.readframes(20160000)
        self.samplenum += 20160000
        #self.wf.readframes(109385200)
        #self.samplenum += 109385200

        # Start the stream
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(self.wf.getsampwidth()), \
                channels = 1,\
                rate = self.wf.getframerate(), \
                output=True, \
                stream_callback=self.Callback)

        self.run()

        while stream.is_active():
            time.sleep(0.1)
            #print(self.samplenum // 48000)

        stream.close()

        p.terminate()

if __name__ == '__main__':
    sys.exit(PlaybackApp().Run())