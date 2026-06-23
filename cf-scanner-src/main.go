package main

import (
	"bufio"
	"crypto/tls"
	"flag"
	"fmt"
	"net"
	"os"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

var (
	inputFile   = flag.String("i", "", "IP list file (required)")
	outputFile  = flag.String("o", "", "Output file for CF proxy hits (default: cf_hits_<timestamp>.txt)")
	stateFile   = flag.String("state", "scanner.state", "Checkpoint file for resume")
	concurrency = flag.Int("c", 500, "Concurrent connections")
	connectTO   = flag.Duration("connect-timeout", 1500*time.Millisecond, "TCP+TLS connect timeout")
	port        = flag.String("p", "443", "Target port")
	sni         = flag.String("sni", "cloudflare.com", "TLS SNI to send")
)

func isCloudflareProxy(ip string) (bool, string) {
	targetHost, targetPort := ip, *port
	if h, p, err := net.SplitHostPort(ip); err == nil {
		targetHost, targetPort = h, p
	}
	target := net.JoinHostPort(targetHost, targetPort)

	conn, err := tls.DialWithDialer(&net.Dialer{Timeout: *connectTO}, "tcp", target, &tls.Config{
		InsecureSkipVerify: true,
		ServerName:         *sni,
	})
	if err != nil {
		return false, target
	}
	defer conn.Close()

	certs := conn.ConnectionState().PeerCertificates
	for _, cert := range certs {
		if strings.Contains(cert.Subject.CommonName, "cloudflare.com") {
			return true, target
		}
		for _, name := range cert.DNSNames {
			if strings.Contains(name, "cloudflare.com") {
				return true, target
			}
		}
	}
	return false, target
}

func countLines(path string) (int, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	count := 0
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		if scanner.Text() != "" {
			count++
		}
	}
	return count, scanner.Err()
}

func streamLines(path string, skip int, out chan<- string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	lineNum := 0
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		lineNum++
		if lineNum <= skip {
			continue
		}
		out <- line
	}
	return scanner.Err()
}

func main() {
	flag.Parse()
	if *inputFile == "" {
		fmt.Fprintln(os.Stderr, "Usage: cf-scanner -i ips.txt [-o hits.txt] [-c 500]")
		os.Exit(1)
	}

	// Auto-generate output filename with timestamp if not specified
	if *outputFile == "" {
		*outputFile = fmt.Sprintf("cf_hits_%s.txt", time.Now().Format("20060102_150405"))
	}
	fmt.Printf("Output: %s\n", *outputFile)

	// Count total lines (fast, low memory)
	fmt.Print("Counting IPs... ")
	total, err := countLines(*inputFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "\nFailed to read %s: %v\n", *inputFile, err)
		os.Exit(1)
	}
	fmt.Printf("%d\n", total)

	// Checkpoint resume (state format: input_file<TAB>skip)
	skip := 0
	if data, err := os.ReadFile(*stateFile); err == nil {
		parts := strings.SplitN(strings.TrimSpace(string(data)), "\t", 2)
		if len(parts) == 2 && parts[0] == *inputFile {
			fmt.Sscanf(parts[1], "%d", &skip)
			if skip > 0 && skip < total {
				fmt.Printf("Resuming from line %d (%.1f%% done)\n", skip, float64(skip)/float64(total)*100)
			} else {
				skip = 0
			}
		} else {
			fmt.Printf("State file is for %q, not %q — starting fresh\n", parts[0], *inputFile)
		}
	}

	out, err := os.OpenFile(*outputFile, os.O_TRUNC|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to open %s: %v\n", *outputFile, err)
		os.Exit(1)
	}
	defer out.Close()

	jobs := make(chan string, *concurrency*2)

	var (
		scanned  atomic.Int64
		hitCount atomic.Int64
		wg       sync.WaitGroup
	)

	// Workers — each with independent TLS dialer
	for i := 0; i < *concurrency; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for ip := range jobs {
				ok, target := isCloudflareProxy(ip)
				n := scanned.Add(1)
				if ok {
					hitCount.Add(1)
					fmt.Fprintf(out, "%s\n", target)
				}
				if n%1000 == 0 {
					os.WriteFile(*stateFile, []byte(fmt.Sprintf("%s\t%d", *inputFile, skip+int(n))), 0644)
				}
			}
		}()
	}

	// Progress reporter
	startTime := time.Now()
	startSkip := int64(skip)
	done := make(chan struct{})
	go func() {
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				n := scanned.Load()
				elapsed := time.Since(startTime)
				rate := float64(n) / elapsed.Seconds()
				remain := int64(total) - startSkip - n
				var eta time.Duration
				if rate > 0 {
					eta = time.Duration(float64(remain)/rate) * time.Second
				}
				pct := float64(startSkip+n) / float64(total) * 100
				fmt.Printf("\r\033[KScanned %d/%d (%.1f%%) | %.0f/s | hits=%d | ETA %s",
					startSkip+n, total, pct, rate, hitCount.Load(), eta.Round(time.Second))
			}
		}
	}()

	// Periodic GC
	gcDone := make(chan struct{})
	go func() {
		ticker := time.NewTicker(15 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-gcDone:
				return
			case <-ticker.C:
				runtime.GC()
			}
		}
	}()

	// Stream IPs from file (low memory)
	go func() {
		if err := streamLines(*inputFile, skip, jobs); err != nil {
			fmt.Fprintf(os.Stderr, "\nError reading input: %v\n", err)
		}
		close(jobs)
	}()

	wg.Wait()
	close(done)
	close(gcDone)

	os.WriteFile(*stateFile, []byte(fmt.Sprintf("%s\t%d", *inputFile, total)), 0644)

	elapsed := time.Since(startTime)
	fmt.Printf("\r\033[KDone! %d/%d (100%%) | %s | hits=%d\n",
		total, total, elapsed.Round(time.Second), hitCount.Load())
	fmt.Printf("Results: %s (%d hits)\n", *outputFile, hitCount.Load())
	os.Remove(*stateFile)
}
