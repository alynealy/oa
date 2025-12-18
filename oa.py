
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import os
from PIL import Image
from io import BytesIO
import hashlib
import re
import json
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed


print("\n Loading URLs from logos.snappy.parquet...")

try:
    df = pd.read_parquet('logos.snappy.parquet')
    print(f"DataFrame shape: {df.shape}")
    all_urls = []
    for i in range(len(df)):
        url = str(df.iloc[i, 0]).strip()
        if url and url.lower() != 'nan' and url != 'None':
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            all_urls.append(url)
        
except Exception as e:
    print(f" Error loading parquet: {e}")
    exit(1)

class LogoHunter:
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        self.request_count = 0
        
    def try_get_logo(self, url):
        self.request_count += 1
        if self.request_count % 50 == 0:
            time.sleep(1) 
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            
            if not domain:
                return None, "invalid_url"
            
            favicon_urls = [
                f"https://www.google.com/s2/favicons?domain={domain}&sz=256",
                f"https://api.faviconkit.com/{domain}/256",
                f"https://logo.clearbit.com/{domain}?size=256",
                f"https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=256",
            ]
            
            for favicon_url in favicon_urls:
                try:
                    response = self.session.get(favicon_url, timeout=5)
                    if response.status_code == 200:
                        content = response.content
                        if 100 < len(content) < 500000:
                            try:
                                Image.open(BytesIO(content))
                                return content, "favicon_service"
                            except:
                                if b'<svg' in content[:200] or content[:4] == b'\x00\x00\x01\x00':
                                    return content, "favicon_service_svg"
                except:
                    continue
            
            try:
                response = self.session.get(url, timeout=15, allow_redirects=True)
                if response.status_code == 200:
                    final_url = response.url
                    base_url = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
                    
                    soup = BeautifulSoup(response.content, 'html.parser')
                    for link in soup.find_all('link', rel=lambda x: x and any(
                        icon in str(x).lower() for icon in ['icon', 'shortcut', 'apple-touch']
                    )):
                        href = link.get('href')
                        if href:
                            try:
                                logo_url = urljoin(final_url, href)
                                resp = self.session.get(logo_url, timeout=5)
                                if resp.status_code == 200:
                                    content = resp.content
                                    if len(content) > 50:
                                        return content, "html_favicon"
                            except:
                                continue
                    
                    for meta in soup.find_all('meta'):
                        prop = meta.get('property', '').lower()
                        content_val = meta.get('content', '')
                        if content_val and ('og:image' in prop or 'twitter:image' in prop):
                            try:
                                logo_url = urljoin(final_url, content_val)
                                resp = self.session.get(logo_url, timeout=5)
                                if resp.status_code == 200:
                                    content = resp.content
                                    if len(content) > 1000:
                                        return content, "og_image"
                            except:
                                continue
                    
                    common_paths = [
                        '/logo.png', '/logo.svg', '/logo.jpg', '/logo.ico',
                        '/favicon.ico', '/favicon.png', '/apple-touch-icon.png',
                        '/images/logo.png', '/img/logo.png', '/static/logo.png',
                        '/assets/logo.png', '/media/logo.png',
                    ]
                    
                    for path in common_paths:
                        try:
                            logo_url = f"{base_url}{path}"
                            resp = self.session.get(logo_url, timeout=5)
                            if resp.status_code == 200:
                                content = resp.content
                                if len(content) > 100:
                                    return content, "common_path"
                        except:
                            continue
                    
                    img_candidates = []
                    for img in soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if src:
                            alt = (img.get('alt') or '').lower()
                            src_lower = src.lower()
                            
                            is_logo = False
                            logo_words = ['logo', 'brand', 'header', 'navbar']
                            for word in logo_words:
                                if word in alt or word in src_lower:
                                    is_logo = True
                                    break
                            
                            if is_logo:
                                img_candidates.append(src)
                    
                    for src in img_candidates[:5]:
                        try:
                            logo_url = urljoin(final_url, src)
                            resp = self.session.get(logo_url, timeout=5)
                            if resp.status_code == 200:
                                content = resp.content
                                if len(content) > 100:
                                    return content, "img_candidate"
                        except:
                            continue
                            
            except Exception as e:
                return None, f"access_error: {str(e)[:30]}"
            
            try:
                base_domain = f"https://{domain}"
                for path in ['/favicon.ico', '/logo.ico', '/apple-touch-icon.png']:
                    try:
                        logo_url = f"{base_domain}{path}"
                        resp = self.session.get(logo_url, timeout=5)
                        if resp.status_code == 200:
                            content = resp.content
                            if len(content) > 50:
                                return content, "domain_root"
                    except:
                        continue
            except:
                pass
            
            return None, "not_found"
            
        except Exception as e:
            return None, f"exception: {str(e)[:30]}"


def process_all_urls(urls, max_workers=40):
    
    hunter = LogoHunter()
    results = {}
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'methods': {},
        'start_time': time.time()
    }
    
    checkpoint_file = 'ultra_checkpoint.pkl'
    
    if os.path.exists(checkpoint_file):
        print("Loading checkpoint...")
        try:
            with open(checkpoint_file, 'rb') as f:
                checkpoint = pickle.load(f)
                results = checkpoint.get('results', {})
                stats = checkpoint.get('stats', stats)
            print(f"Loaded {len(results):,} results from checkpoint")
        except Exception as e:
            print(f"Could not load checkpoint: {e}")
    
    processed_urls = set(results.keys())
    urls_to_process = [url for url in urls if url not in processed_urls]
    
    print(f"Already processed: {len(processed_urls):,}")
    print(f"Remaining to process: {len(urls_to_process):,}")
    
    if not urls_to_process:
        print("All URLs already processed!")
        return results, stats
    
    batch_size = 200
    total_batches = (len(urls_to_process) + batch_size - 1) // batch_size
    
    for batch_num in range(total_batches):
        batch_start = batch_num * batch_size
        batch_end = min(batch_start + batch_size, len(urls_to_process))
        batch = urls_to_process[batch_start:batch_end]
        
        print(f"\nProcessing batch {batch_num + 1}/{total_batches} "
              f"({batch_start + 1:,}-{batch_end:,})")
        
        batch_results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(hunter.try_get_logo, url): url for url in batch}
            
            completed = 0
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                
                try:
                    logo_bytes, method = future.result()
                    stats['total'] += 1
                    
                    if logo_bytes is not None:
                        stats['success'] += 1
                        stats['methods'][method] = stats['methods'].get(method, 0) + 1
                        
                        md5_hash = hashlib.md5(logo_bytes).hexdigest()[:16]
                        
                        batch_results[url] = {
                            'bytes': logo_bytes,
                            'method': method,
                            'size': len(logo_bytes),
                            'md5': md5_hash,
                            'timestamp': time.time()
                        }
                    else:
                        stats['failed'] += 1
                        batch_results[url] = {
                            'bytes': None,
                            'method': method,
                            'error': 'No logo found'
                        }
                    if completed % 20 == 0 or completed == len(batch):
                        elapsed = time.time() - stats['start_time']
                        success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
                        
                        print(f" Progress: {batch_start + completed:,}/{len(urls_to_process):,} "
                              f"| Success: {stats['success']:,} ({success_rate:.1f}%)")
                
                except Exception as e:
                    stats['total'] += 1
                    stats['failed'] += 1
                    batch_results[url] = {
                        'bytes': None,
                        'method': 'exception',
                        'error': str(e)[:100]
                    }
        
        results.update(batch_results)
        
        try:
            with open(checkpoint_file, 'wb') as f:
                pickle.dump({
                    'results': results,
                    'stats': stats,
                    'processed_count': len(results)
                }, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"  Checkpoint saved ({len(results):,} total results)")
        except Exception as e:
            print(f"  Could not save checkpoint: {e}")
        
        if batch_num < total_batches - 1:
            time.sleep(2)
    if os.path.exists(checkpoint_file):
        try:
            os.remove(checkpoint_file)
        except:
            pass
    
    elapsed_total = time.time() - stats['start_time']
    print(f"\nProcessing completed in {elapsed_total/60:.1f} minutes")
    
    return results, stats


def save_all_in_single_folder(results, urls, folder_name='Logos'):
    print(f"\nSaving ALL logos to '{folder_name}' folder...")
    os.makedirs(folder_name, exist_ok=True)
    saved_count = 0
    failed_count = 0

    metadata = {
        'total_urls': len(urls),
        'processed_urls': len(results),
        'saved_logos': 0,
        'failed_logos': 0,
        'success_rate': 0,
        'processing_date': time.ctime(),
        'files': []
    }
    
    for i, url in enumerate(urls, 1):
        try:
            data = results.get(url, {'bytes': None, 'method': 'not_processed'})
            file_number = f"{i:04d}"  
            if data.get('bytes'):
                bytes_data = data['bytes']
                extension = 'png'  
                try:
                    img = Image.open(BytesIO(bytes_data))
                    if img.format:
                        extension = img.format.lower()
                except:
                    if bytes_data[:4] == b'<svg':
                        extension = 'svg'
                    elif bytes_data[:4] == b'\x00\x00\x01\x00':
                        extension = 'ico'
                    elif bytes_data[:8] == b'\x89PNG\r\n\x1a\n':
                        extension = 'png'
                    elif bytes_data[:3] == b'\xff\xd8\xff':
                        extension = 'jpg'
                    elif bytes_data[:4] == b'RIFF' and bytes_data[8:12] == b'WEBP':
                        extension = 'webp'
                
                filename = f"{file_number}.{extension}"
                filepath = os.path.join(folder_name, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(bytes_data)
                
                saved_count += 1
                parsed = urlparse(url)
                domain = parsed.netloc or url[:50]
                
                metadata['files'].append({
                    'index': i,
                    'filename': filename,
                    'original_url': url,
                    'domain': domain,
                    'method': data.get('method', 'unknown'),
                    'size': len(bytes_data),
                    'md5': data.get('md5', ''),
                    'status': 'success'
                })
                
                if saved_count % 100 == 0:
                    print(f"Saved {saved_count:,} logos...")
                    
            else:
                filename = f"{file_number}_FAILED.txt"
                filepath = os.path.join(folder_name, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"URL: {url}\n")
                    f.write(f"Status: FAILED\n")
                    f.write(f"Error: {data.get('error', 'No logo found')}\n")
                    f.write(f"Method: {data.get('method', 'unknown')}\n")
                    f.write(f"Index: {i}\n")
                    f.write(f"Timestamp: {time.ctime()}\n")
                
                failed_count += 1
                metadata['files'].append({
                    'index': i,
                    'filename': filename,
                    'original_url': url,
                    'status': 'failed',
                    'error': data.get('error', 'No logo found'),
                    'method': data.get('method', 'unknown')
                })
                
        except Exception as e:
            failed_count += 1
            print(f" Error saving logo {i}: {str(e)[:50]}")
    
    metadata['saved_logos'] = saved_count
    metadata['failed_logos'] = failed_count
    metadata['success_rate'] = (saved_count / len(urls) * 100) if urls else 0
    
    metadata_file = os.path.join(folder_name, '_METADATA.json')
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return saved_count

if __name__ == "__main__":
    print(f"\nVERIFICATION:")
    print(f"   Total URLs loaded: {len(all_urls):,}")
    
    start_time = time.time()
    all_results, stats = process_all_urls(all_urls, max_workers=50)
    
    success_count = stats['success']
    total_attempts = stats['total']
    success_rate = (success_count / len(all_urls) * 100) if all_urls else 0
    
    saved_count = save_all_in_single_folder(all_results, all_urls, 'LOGOS')