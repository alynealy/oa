import os
import numpy as np
from PIL import Image, ImageChops, ImageStat, ImageFilter
import imagehash
import hashlib
import json
import time
import warnings
import re
from collections import defaultdict
from io import BytesIO

warnings.filterwarnings('ignore')


class LogoCluster:
    def __init__(self, logos_folder="LOGOS"):
        self.logos_folder = logos_folder
        self.cache = {}
        
    def load_all_images(self):
        print("Loading all images...")   
        image_files = []
        image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.ico'}
        for file in os.listdir(self.logos_folder):
            ext = os.path.splitext(file)[1].lower()
            if ext in image_extensions:
                image_files.append(file)
        
        return image_files
    
    def detect_file_type(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                header = f.read(512).decode('utf-8', errors='ignore')
                if '<?xml' in header or '<svg' in header or 'svg' in header.lower():
                    return 'svg'
                f.seek(0)
                png_signature = f.read(8)
                if png_signature == b'\x89PNG\r\n\x1a\n':
                    return 'png'
                f.seek(0)
                jpeg_signature = f.read(3)
                if jpeg_signature == b'\xff\xd8\xff':
                    return 'jpeg'
                ext = os.path.splitext(filepath)[1].lower()
                return ext[1:] if ext else 'unknown'
                
        except:
            return 'unknown'
    
    def load_image(self, filepath):
        try:
            real_type = self.detect_file_type(filepath)
            if real_type == 'svg':
                return self.load_svg_file(filepath)
            else:
                return Image.open(filepath)
                
        except Exception as e:
            print(f"Error loading {os.path.basename(filepath)}: {e}")
            return Image.new('RGB', (64, 64), color=(200, 200, 200))
    
    def load_svg_file(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            width = 64
            height = 64
            width_match = re.search(r'width=["\']([^"\']+)["\']', content)
            height_match = re.search(r'height=["\']([^"\']+)["\']', content)
            viewbox_match = re.search(r'viewBox=["\']([^"\']+)["\']', content)
            
            if width_match and height_match:
                try:
                    w = re.sub(r'[^\d.]', '', width_match.group(1))
                    h = re.sub(r'[^\d.]', '', height_match.group(1))
                    if w and h:
                        width = int(float(w))
                        height = int(float(h))
                except:
                    pass
            elif viewbox_match:
                try:
                    parts = viewbox_match.group(1).split()
                    if len(parts) >= 4:
                        width = int(float(parts[2]))
                        height = int(float(parts[3]))
                except:
                    pass
            color = self.extract_svg_color(content)
            img = Image.new('RGB', (width, height), color=color)
            return img
            
        except Exception as e:
            print(f"Error processing SVG {os.path.basename(filepath)}: {e}")
            return Image.new('RGB', (64, 64), color=(150, 150, 150))
    
    def extract_svg_color(self, svg_content):
        try:
            color_matches = re.findall(r'fill[:=]["\']([^"\']+)["\']', svg_content, re.IGNORECASE)
            
            if color_matches:
                for color_str in color_matches:
                    color = self.parse_color(color_str)
                    if color:
                        return color
            style_matches = re.findall(r'style=["\'][^"\']*fill:([^;]+)', svg_content, re.IGNORECASE)
            for style in style_matches:
                color = self.parse_color(style.strip())
                if color:
                    return color
            return (100, 100, 200) 
            
        except:
            return (100, 100, 200)
    
    def parse_color(self, color_str):
        try:
            color_str = color_str.strip().lower()
            rgb_match = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color_str)
            if rgb_match:
                return tuple(int(x) for x in rgb_match.groups())
            if color_str.startswith('#'):
                hex_color = color_str[1:]
                if len(hex_color) == 3:
                    hex_color = ''.join(c*2 for c in hex_color)
                if len(hex_color) == 6:
                    return (
                        int(hex_color[0:2], 16),
                        int(hex_color[2:4], 16),
                        int(hex_color[4:6], 16)
                    )
            color_map = {
                'red': (255, 0, 0),
                'green': (0, 255, 0),
                'blue': (0, 0, 255),
                'yellow': (255, 255, 0),
                'orange': (255, 165, 0),
                'purple': (128, 0, 128),
                'black': (0, 0, 0),
                'white': (255, 255, 255),
                'gray': (128, 128, 128),
                'grey': (128, 128, 128),
            }
            
            if color_str in color_map:
                return color_map[color_str]
            
            return None
            
        except:
            return None
    
    def get_image_signature(self, filename):
        try:
            path = os.path.join(self.logos_folder, filename)
            with open(path, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            img = self.load_image(path)
            img_resized = img.resize((64, 64), Image.Resampling.LANCZOS)
            if img_resized.mode != 'RGB':
                img_resized = img_resized.convert('RGB')
            
            img_array = np.array(img_resized)
            real_type = self.detect_file_type(path)
            ext = os.path.splitext(filename)[1].lower()
            signature = {
                'filename': filename,
                'hash': file_hash,
                'real_type': real_type,
                'extension': ext,
                'size': img.size,
                'aspect_ratio': img.size[0] / max(img.size[1], 1),
                'is_svg_like': real_type == 'svg' or ext == '.svg',
            }
            try:
                signature['phash'] = str(imagehash.phash(img_resized))
                signature['ahash'] = str(imagehash.average_hash(img_resized))
            except:
                signature['phash'] = '0' * 16  
                signature['ahash'] = '0' * 16
            if img_array.size > 0:
                signature['avg_color'] = tuple(img_array.mean(axis=(0, 1)).astype(int))
                if len(img_array.shape) == 3:
                    gray = np.dot(img_array[...,:3], [0.299, 0.587, 0.114])
                else:
                    gray = img_array
                
                signature['brightness'] = float(gray.mean())
                signature['contrast'] = float(gray.std())
            else:
                signature['avg_color'] = (128, 128, 128)
                signature['brightness'] = 128
                signature['contrast'] = 0
            
            return signature
            
        except Exception as e:
            print(f"Error getting signature for {filename}: {e}")
            return {
                'filename': filename,
                'hash': 'error',
                'real_type': 'error',
                'extension': os.path.splitext(filename)[1].lower(),
                'size': (64, 64),
                'aspect_ratio': 1.0,
                'is_svg_like': False,
                'phash': '0' * 16,
                'ahash': '0' * 16,
                'avg_color': (128, 128, 128),
                'brightness': 128,
                'contrast': 0
            }
    
    def compare_signatures(self, sig1, sig2):
        if not sig1 or not sig2:
            return 0.0
        cache_key = (sig1['filename'], sig2['filename'])
        if cache_key in self.cache:
            return self.cache[cache_key]
        if sig1['hash'] != 'error' and sig2['hash'] != 'error' and sig1['hash'] == sig2['hash']:
            self.cache[cache_key] = 1.0
            return 1.0
        
        similarity_scores = []
        weights = []
        if sig1['phash'] != '0' * 16 and sig2['phash'] != '0' * 16:
            try:
                hash1 = imagehash.hex_to_hash(sig1['phash'])
                hash2 = imagehash.hex_to_hash(sig2['phash'])
                hash_diff = hash1 - hash2
                hash_sim = max(0, 1 - (hash_diff / 64))
                similarity_scores.append(hash_sim)
                weights.append(0.4)
            except:
                pass
        color1 = np.array(sig1['avg_color'])
        color2 = np.array(sig2['avg_color'])
        color_dist = np.linalg.norm(color1 - color2)
        color_sim = max(0, 1 - (color_dist / 441.67))
        similarity_scores.append(color_sim)
        weights.append(0.3)
        bright_diff = abs(sig1['brightness'] - sig2['brightness'])
        bright_sim = max(0, 1 - (bright_diff / 255))
        similarity_scores.append(bright_sim)
        weights.append(0.1)
        ar_diff = abs(sig1['aspect_ratio'] - sig2['aspect_ratio'])
        ar_sim = max(0, 1 - ar_diff)
        similarity_scores.append(ar_sim)
        weights.append(0.1)
        if sig1['real_type'] == sig2['real_type']:
            similarity_scores.append(0.8) 
            weights.append(0.1)
        total_weight = sum(weights)
        if total_weight == 0:
            similarity = 0.0
        else:
            similarity = sum(s * w for s, w in zip(similarity_scores, weights)) / total_weight
        
        self.cache[cache_key] = similarity
        return similarity
    
    def cluster_logos(self, image_files):
        print("Clustering logos...")
        signatures = {}
        valid_files = []
        print("Extracting signatures...")
        for i, filename in enumerate(image_files):
            signature = self.get_image_signature(filename)
            signatures[filename] = signature
            valid_files.append(filename)
            
            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{len(image_files)} files")
        
        print(f"Got signatures for {len(valid_files)} logos")
        groups = []
        assigned = set()
        for i, file1 in enumerate(valid_files):
            if file1 in assigned:
                continue
            current_group = [file1]
            assigned.add(file1)
            sig1 = signatures[file1]
            for file2 in valid_files[i+1:]:
                if file2 in assigned:
                    continue
                
                sig2 = signatures[file2]
                similarity = self.compare_signatures(sig1, sig2)
                if similarity >= 0.7:
                    current_group.append(file2)
                    assigned.add(file2)
            if len(current_group) > 1:
                groups.append({
                    'type': 'similar',
                    'files': current_group,
                    'count': len(current_group),
                    'avg_similarity': self.calculate_group_similarity(current_group, signatures)
                })
            else:
                groups.append({
                    'type': 'unique',
                    'files': current_group,
                    'count': 1,
                    'avg_similarity': 1.0
                })
            
            if len(groups) % 50 == 0:
                print(f"  Created {len(groups)} groups, processed {len(assigned)}/{len(valid_files)} logos")
        print("Checking for exact duplicates...")
        hash_groups = defaultdict(list)
        for filename, sig in signatures.items():
            if sig['hash'] != 'error':
                hash_groups[sig['hash']].append(filename)
        final_groups = []
        processed = set()
        
        for files in hash_groups.values():
            if len(files) > 1 and all(f not in processed for f in files):
                final_groups.append({
                    'type': 'exact',
                    'files': files,
                    'count': len(files),
                    'avg_similarity': 1.0
                })
                processed.update(files)
        for group in groups:
            group_files = set(group['files'])
            if not group_files.intersection(processed):
                final_groups.append(group)
                processed.update(group_files)
        all_files_set = set(valid_files)
        remaining = all_files_set - processed
        for file in remaining:
            final_groups.append({
                'type': 'unique',
                'files': [file],
                'count': 1,
                'avg_similarity': 1.0
            })
        
        print(f"Created {len(final_groups)} total groups")
        print(f"ll {len(valid_files)} logos are in groups")
        
        return final_groups
    
    def calculate_group_similarity(self, files, signatures):
        if len(files) <= 1:
            return 1.0
        
        similarities = []
        for i in range(len(files)):
            for j in range(i+1, len(files)):
                sig1 = signatures[files[i]]
                sig2 = signatures[files[j]]
                similarity = self.compare_signatures(sig1, sig2)
                similarities.append(similarity)
        
        return np.mean(similarities) if similarities else 0.0
    
    def analyze_and_save(self, groups, total_files):
        print("\nANALYSIS RESULTS")
        
        total_groups = len(groups)
        total_logos = sum(g['count'] for g in groups)
        
        print(f"Total logos: {total_files}")
        print(f"Total groups: {total_groups}")
        print(f"Logos in groups: {total_logos}")
        group_types = defaultdict(int)
        group_sizes = []
        
        for group in groups:
            group_types[group['type']] += 1
            group_sizes.append(group['count'])
        
        print(f"\nGROUP TYPE DISTRIBUTION:")
        for type_name, count in sorted(group_types.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total_groups) * 100
            print(f"  {type_name:15s}: {count:4d} groups ({percentage:5.1f}%)")
        
        print(f"\nGROUP SIZE DISTRIBUTION:")
        size_ranges = [(1, 1), (2, 3), (4, 6), (7, 10), (11, 20), (21, 50), (51, 1000)]
        
        for min_s, max_s in size_ranges:
            count = sum(1 for s in group_sizes if min_s <= s <= max_s)
            if count > 0:
                percentage = (count / total_groups) * 100
                print(f"  {min_s:2d}-{max_s:3d} logos: {count:4d} groups ({percentage:5.1f}%)")
        groups_sorted = sorted(groups, key=lambda x: x['count'], reverse=True)
        
        for i, group in enumerate(groups_sorted[:20]):
            print(f"{i+1:2d}. {group['type']:15s} - {group['count']:3d} logos (sim: {group['avg_similarity']:.2f})")
            if group['count'] <= 3:
                print(f"     Files: {', '.join(group['files'][:3])}")
        print(f"\nSaving results...")
        
        output = {
            'metadata': {
                'total_files': total_files,
                'total_groups': total_groups,
                'total_logos_in_groups': total_logos,
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'method': 'smart_clustering_svg_aware'
            },
            'groups': {}
        }
        
        for i, group in enumerate(groups):
            group_name = f"group_{i+1:04d}"
            output['groups'][group_name] = group
        
        with open('logo_gorups.json', 'w') as f:
            json.dump(output, f, indent=2)
        with open('logo_summary.txt', 'w') as f:
            self._write_summary(f, output, groups)
        
        return output
    
    def _write_summary(self, f, output, groups):
        f.write("LOGO CLUSTERING RESULTS (SVG AWARE)\n")
        
        meta = output['metadata']
        f.write(f"Total files processed: {meta['total_files']}\n")
        f.write(f"Total groups created: {meta['total_groups']}\n")
        f.write(f"Method: {meta['method']}\n")
        f.write(f"Date: {meta['created_at']}\n\n")
        group_types = defaultdict(int)
        group_sizes = [g['count'] for g in groups]
        
        for group in groups:
            group_types[group['type']] += 1
        
        f.write("GROUP STATISTICS:\n")
        for type_name, count in sorted(group_types.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(groups)) * 100
            f.write(f"  {type_name:15s}: {count:4d} ({percentage:5.1f}%)\n")
        
        f.write(f"\nAverage group size: {np.mean(group_sizes):.2f}\n")
        f.write(f"Largest group: {max(group_sizes)} logos\n")
        f.write(f"Singleton groups: {sum(1 for s in group_sizes if s == 1)}\n")
        
        groups_sorted = sorted(groups, key=lambda x: x['count'], reverse=True)
        
        for i, group in enumerate(groups_sorted):
            f.write(f"\nGROUP {i+1}: {group['type']} - {group['count']} logos\n")
            f.write(f"Average similarity: {group['avg_similarity']:.3f}\n")
            
            files = group['files']
            if len(files) <= 10:
                for j, file in enumerate(files, 1):
                    f.write(f"{j:3d}. {file}\n")
            else:
                for j in range(min(5, len(files))):
                    f.write(f"{j+1:3d}. {files[j]}\n")
                f.write(f"... and {len(files) - 5} more\n")


if __name__ == "__main__":
    start_time = time.time()
    if not os.path.exists("LOGOS"):
        print("ERROR: LOGOS folder not found!")
        exit(1)
    clusterer = LogoCluster("LOGOS")
    image_files = clusterer.load_all_images()
    
    if not image_files:
        print("No image files found!")
        exit(1)
    print(f"\nProcessing {len(image_files)} files...")
    groups = clusterer.cluster_logos(image_files)
    results = clusterer.analyze_and_save(groups, len(image_files))
    
    total_time = time.time() - start_time