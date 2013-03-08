# -*- coding: utf-8 -*-
#!/usr/bin/env python

from __future__ import division
import sys
import os
import itertools
import time
import signal
import httplib2
import math
import json
import urllib
import gevent
from gevent.queue import Queue, Empty
from gevent.queue import Queue
from gevent.pool import Pool

__version__ = '0.1'


signal.signal(signal.SIGQUIT, gevent.shutdown)

class Result(object):
    def __init__(self, time, size, status, detail_time=None):
        self.time = time
        self.size = size
        self.status = status
        self.detail_time = detail_time
    
    def __repr__(self):
        return 'Result(%.5f, %d, %d, detail_time=%r)' % (self.time, self.size,
                                                        self.status, self.detail_time)
tasks = Queue()
gets = Queue()
http = httplib2.Http()

def get_url(url):
    start = time.time()
    size = status = 0
    try:
        resp, content = http.request(url)
        size = len(content)
        status = resp.status
    except:
        return None
    total_time = time.time() - start
    result = Result(total_time, size, status)
    return result

def work(c):
    
    while not tasks.empty():
        url = tasks.get()
        gevent.sleep(0)
        r = get_url(url)
        gets.put(r)


def boss(urls, n):
    if isinstance(urls, basestring):
        urls = itertools.repeat(urls)
    elif isinstance(urls, list):
        urls = itertools.cycle(urls)
    url_iter = urls
    for i in xrange(n):
        try:
            a = url_iter.next()
            tasks.put_nowait(a)
        except:
            pass

#
class ResultStats(object):
    def __init__(self):
        self.results = []
        self.start_time = time.time()
        self.total_wall_time = -1
    
    def stop(self):
        self.total_wall_time = time.time() - self.start_time
    
    def add(self, result):
        if result is not None:
            self.results.append(result)
        else:
            self.results.append(Result(0, 0, -1))
    
    @property
    def failed_requests(self):
        return sum(1 for r in self.results if int(r.status) != 200)
    
    @property
    def total_req_time(self):
        return sum(r.time for r in self.results)

    @property
    def avg_req_time(self):
        return self.total_req_time / len(self.results)
    
    @property
    def total_req_length(self):
        return sum(r.size for r in self.results)
    
    @property
    def avg_req_length(self):
        return self.total_req_length / len(self.results)
    
    def distribution(self):
        results = sorted(r.time for r in self.results)
        dist = []
        n = len(results)
        for p in (50, 66, 75, 80, 90, 95, 98, 99):
            i = p/100 * n - 0.001 #return right time if matched
            if i >= n:
                i = n-1
            else:
                i = int(i)
            dist.append((p, results[i]))
        dist.append((100, results[-1]))
        return dist
    
    def connection_times(self):
        if self.results[0].detail_time is None:
            return None
        connect = [r.detail_time[0] for r in self.results]
        process = [r.detail_time[1] for r in self.results]
        wait = [r.detail_time[2] for r in self.results]
        total = [r.time for r in self.results]
        
        results = []
        for data in (connect, process, wait, total):
            results.append((min(data), mean(data), std_deviation(data),
                            median(data), max(data)))
        return results

square_sum = lambda l: sum(x*x for x in l)
mean = lambda l: sum(l)/len(l)
deviations = lambda l, mean: [x-mean for x in l]
def std_deviation(l):
    n = len(l)
    if n == 1:
        return 0
    return math.sqrt(square_sum(deviations(l, mean(l)))/(n-1))
median = lambda l: sorted(l)[int(len(l)//2)]


#py Benchmarking
class PB(object):
    def __init__(self, urls, c=1, n=1, T=None, p=None, out=sys.stdout):
        self.c = c
        self.n = n
        self.urls = urls
        self.out = out

    def start(self):
        out = self.out
        print >>out, 'Benchmarking ....'
        out.flush()
        

        stats = ResultStats()

        gevent.spawn(boss,self.urls, self.n).join()

        pool = Pool(self.c)
        for i in range(self.c):
            pool.spawn(work, i)
        pool.join()
        
        while not gets.empty():
            c = gets.get()
            stats.add(c)
        stats.stop()
        
        print >>out, 'Average Document Length: %.0f bytes' % (stats.avg_req_length,)
        print >>out
        print >>out, 'Concurrency Level:    %d' % (self.c,)
        print >>out, 'Time taken for tests: %.3f seconds' % (stats.total_wall_time,)
        print >>out, 'Complete requests:    %d' % (len(stats.results)-stats.failed_requests,)
        print >>out, 'Failed requests:      %d' % (stats.failed_requests,)
        print >>out, 'Total transferred:    %d bytes' % (stats.total_req_length,)
        print >>out, 'Requests per second:  %.2f [#/sec] (mean)' % (len(stats.results)/
                                                                    stats.total_wall_time,)
        print >>out, 'Time per request:     %.3f [ms] (mean)' % (stats.avg_req_time*1000,)
        print >>out, 'Time per request:     %.3f [ms] (mean,'\
                     ' across all concurrent requests)' % (stats.avg_req_time*1000/self.c,)
        print >>out, 'Transfer rate:        %.2f [Kbytes/sec] received' % \
                      (stats.total_req_length/stats.total_wall_time/1024,)
        print >>out
        
        connection_times = stats.connection_times()
        if connection_times is not None:
            print >>out, 'Connection Times (ms)'
            print >>out, '              min  mean[+/-sd] median   max'
            names = ('Connect', 'Processing', 'Waiting', 'Total')
            for name, data in zip(names, connection_times):
                t_min, t_mean, t_sd, t_median, t_max = [v*1000 for v in data] # to [ms]
                t_min, t_mean, t_median, t_max = [round(v) for v in t_min, t_mean,
                                                  t_median, t_max]
                print >>out, '%-11s %5d %5d %5.1f %6d %7d' % (name+':', t_min, t_mean, t_sd,
                                                               t_median, t_max)
            print >>out

        print >>out, 'Percentage of the requests served within a certain time (ms)'
        for percent, seconds in stats.distribution():
            print >>out, ' %3d%% %6.0f' % (percent, seconds*1024),
            if percent == 100:
                print >>out, '(longest request)'
            else:
                print >>out





#main
def main():
    from optparse import OptionParser
    usage = "usage: %prog [options] url(s)"
    parser = OptionParser(usage=usage, version='%prog ' + __version__)
    parser.add_option('-c', None, dest='c', type='int', default=1,
                      help='Number of multiple requests to perform at a time')
    parser.add_option('-n', None, dest='n', type='int', default=1,
                      help='total number of requests')
    parser.add_option('-f', '--url-file', dest='url_file', default=None,
                      help='''file with one URL per line''')
    parser.add_option('-o', '--out-file', dest='out_file', default=None,
                      help='''file with one URL per line''')
    
    (options, args) = parser.parse_args()

    if options.url_file is not None:
        urls = [line.strip() for line in open(options.url_file)]
    elif len(args) > 0:
        urls = args
    else:
        parser.error('need one or more urls or -f argument')

    if options.out_file is None:
        out = sys.stdout
    else:
        out = open(options.out_file, 'aw')

    pb = PB(urls, options.c, options.n, out)
    pb.start()

    


if __name__ == '__main__':
    main()
