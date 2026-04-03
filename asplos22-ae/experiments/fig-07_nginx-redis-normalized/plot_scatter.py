import sys
import os
import csv
import matplotlib.pyplot as plt


def apply_search_style():
  plt.rcParams.update({
    'font.family': 'Times New Roman',
    'font.size': 10,
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'legend.fontsize': 9,
    'axes.edgecolor': '#262626',
    'axes.linewidth': 1.1,
    'text.color': '#262626',
    'svg.fonttype': 'none',
  })

def check_equal_permutations(perm1, perm2):
    res1 = ""
    for i in perm1.keys():
        res1 += perm1[i]
    res2 = ""
    for j in perm2.keys():
        res2 += perm2[j]
    return res1 == res2
        
def collate(permutations_file_redis=None, permutations_file_nginx=None, results_file_nginx=None, results_file_redis=None):
  if not os.path.isfile(permutations_file_nginx):
    print("Cannot find: %s" % permutations_file_nginx)
    sys.exit(1)

  if not os.path.isfile(permutations_file_redis):
    print("Cannot find: %s" % permutations_file_redis)
    sys.exit(1)
 
  permutations_nginx = {}
 
  with open(permutations_file_nginx, 'r') as csvfile:
    print("Processing %s..." % permutations_file_nginx)
    csvdata = csv.reader(csvfile, delimiter=",")
    cols = next(csvdata)
    for row in csvdata:
      permutations_nginx[row[0]] = (dict(zip(cols[1:], row[1:])))
      permutations_nginx[row[0]]['spec'] = (dict(zip(cols[1:], row[1:])))

  max_nginx = 0
  with open(results_file_nginx, 'r') as csvfile:
    print("Processing %s..." % results_file_nginx)
    csvdata = csv.reader(csvfile, delimiter=",")
    cols = next(csvdata)
    for row in csvdata:
      data = dict(zip(cols[1:], row[1:]))
 
      if row[0] not in permutations_nginx:
        print("Missing result from permutation: %s" % row[0])
        continue
 
      if data["METHOD"] not in permutations_nginx[row[0]]:
        permutations_nginx[row[0]][data["METHOD"]] = {}
      
      if data["CHUNK"] not in permutations_nginx[row[0]][data["METHOD"]]:
        permutations_nginx[row[0]][data["METHOD"]][data["CHUNK"]] = []
 
      if float(data["VALUE"]) > max_nginx:
          max_nginx = float(data["VALUE"])

      permutations_nginx[row[0]][data["METHOD"]][data["CHUNK"]].append(
        float(data["VALUE"])
      )


  permutations_redis = {}
 
  with open(permutations_file_redis, 'r') as csvfile:
    print("Processing %s..." % permutations_file_redis)
    csvdata = csv.reader(csvfile, delimiter=",")
    cols = next(csvdata)
    for row in csvdata:
      permutations_redis[row[0]] = (dict(zip(cols[1:], row[1:])))
      permutations_redis[row[0]]['spec'] = (dict(zip(cols[1:], row[1:])))

  max_redis = 0

  with open(results_file_redis, 'r') as csvfile:
    print("Processing %s..." % results_file_redis)
    csvdata = csv.reader(csvfile, delimiter=",")
    cols = next(csvdata)
    for row in csvdata:
      data = dict(zip(cols[1:], row[1:]))
 
      if row[0] not in permutations_redis:
        print("Missing result from permutation: %s" % row[0])
        continue
 
      if data["METHOD"] not in permutations_redis[row[0]]:
        permutations_redis[row[0]][data["METHOD"]] = {}
      
      if data["CHUNK"] not in permutations_redis[row[0]][data["METHOD"]]:
        permutations_redis[row[0]][data["METHOD"]][data["CHUNK"]] = []
      if float(data["VALUE"]) > max_redis:
          max_redis = float(data["VALUE"])
      permutations_redis[row[0]][data["METHOD"]][data["CHUNK"]].append(
        float(data["VALUE"])
      )
  
  x_1 = []
  y_1 = []
  x_2 = []
  y_2 = []
  x_3 = []
  y_3 = []
  colors_1 = []
  colors_2 = []
  colors_3 = []
  for i in permutations_redis.keys():
      for j in permutations_nginx.keys():
          #print(permutations_nginx[j])
          if check_equal_permutations(permutations_redis[i]['spec'], permutations_nginx[j]['spec']):
              if "GET" in permutations_redis[i] and "REQ" in permutations_nginx[j]:
                  is_2 = 0
                  is_three = 0
                  is_two = 0
                  for k in permutations_nginx[j]:
                      if "COMPARTMENT" in k and k != "NUM_COMPARTMENTS":
                          if permutations_nginx[j][k] == '3':
                              is_three = 1

                          if permutations_nginx[j][k] == '2':
                              is_two = 1


                  if is_three:
                      colors_3.append('b')
                      x_3.append(sum(permutations_redis[i]["GET"]["5"]) / (max_redis * len(permutations_redis[i]["GET"]["5"])))
                      y_3.append(sum(permutations_nginx[j]["REQ"]["5"]) / (max_nginx * len(permutations_nginx[j]["REQ"]["5"])))
                  else:
                      if is_two:
                        colors_2.append('g')
                        x_2.append(sum(permutations_redis[i]["GET"]["5"]) / (max_redis * len(permutations_redis[i]["GET"]["5"])))
                        y_2.append(sum(permutations_nginx[j]["REQ"]["5"]) / (max_nginx * len(permutations_nginx[j]["REQ"]["5"])))
                      else:
                        colors_1.append('k')
                        x_1.append(sum(permutations_redis[i]["GET"]["5"]) / (max_redis * len(permutations_redis[i]["GET"]["5"])))
                        y_1.append(sum(permutations_nginx[j]["REQ"]["5"]) / (max_nginx * len(permutations_nginx[j]["REQ"]["5"])))

                  #print("{} {}### {} {}".format(i,permutations_redis[i]["GET"]["5"],j,permutations_nginx[j]["REQ"]["5"]))
 
  apply_search_style()
  fig, ax = plt.subplots(figsize=(9.2, 3.0))
  fig.patch.set_facecolor('white')
  ax.set_facecolor('white')
  for spine in ax.spines.values():
    spine.set_linewidth(1.1)
    spine.set_color('#262626')
  ax.scatter(x_1, y_1, c='#4c78a8', edgecolors='#2f2f2f', linewidths=0.35, s=20, alpha=0.92, marker="o", label="1 compartment", zorder=3)
  ax.scatter(x_2, y_2, c='#1f9d8a', edgecolors='#2f2f2f', linewidths=0.35, s=22, alpha=0.92, marker="^", label="2 compartments", zorder=3)
  ax.scatter(x_3, y_3, c='#e67e22', edgecolors='#2f2f2f', linewidths=0.35, s=22, alpha=0.92, marker="s", label="3 compartments", zorder=3)
  leg = ax.legend(loc='lower right', frameon=True, facecolor='white', edgecolor='#262626', framealpha=1.0, fancybox=False)
  leg.get_frame().set_linewidth(1.0)
  ax.plot((0, 1), (0, 1), color='#2f4e72', linestyle='--', linewidth=1.25, zorder=2, dashes=(3.7, 1.6))
  ax.set_xlim(0, 1)
  ax.set_ylim(0, 1)
  ax.tick_params(axis='x', colors='#262626', width=1.1)
  ax.tick_params(axis='y', colors='#262626', width=1.1)
  ax.grid(False)
  plt.ylabel("Nginx norm. perf.")
  plt.xlabel("Redis norm. perf.")
  out_path = "/out/nginx-redis-scatter.svg"
  if len(sys.argv) >= 6:
    out_path = sys.argv[5]

  out_dir = os.path.dirname(out_path)
  if out_dir:
    os.makedirs(out_dir, exist_ok=True)

  ext = os.path.splitext(out_path)[1].lower()
  fmt = "png" if ext == ".png" else "svg"
  plt.tight_layout()
  plt.savefig(out_path, format=fmt, bbox_inches="tight")
if __name__ == "__main__":
  if len(sys.argv) < 5:
    print("Usage: plot_scatter.py REDIS_PERM NGINX_PERM REDIS_CSV NGINX_CSV [OUT_FILE]")
    sys.exit()
    
  permutations = collate(
    permutations_file_redis=sys.argv[1],
    permutations_file_nginx=sys.argv[2],
    results_file_redis=sys.argv[3],
    results_file_nginx=sys.argv[4],
    
  ) 

