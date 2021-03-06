import cherrypy
import time
import os
import redis
import json
import uuid
import subprocess

redis = redis.Redis()

index_html = """
<!DOCTYPE html>
<html>
<head>
<title>Musicazoo WIP</title>
<style>
body {
	color: #f3fde1;
	background-color: #406873;
}
</style>
</head>
<body>
<h1>Musicazoo</h1>
<p>Volume: <button id="sub">-</button><span id="vol">loading</span><button id="add">+</button></p>
<p>Use this form to queue new videos:</p>
<input type="text" id="youtube_id" placeholder="youtube search or ID"> <button id="submit">Queue</button> <button id="suggest">Suggest</button>
<ul id="suggestions">
</ul>
<p>Queued items:</p>
<ul id="queue">
<li>Loading...</li>
</ul>
<script>
  (function() {
    function json_request(cb, err, endpoint) {
      var req = new XMLHttpRequest();
      req.addEventListener("load", function() {
        var json = JSON.parse(this.responseText);
        if (json) {
          cb(json);
        } else {
          err("bad json from endpoint " + endpoint);
        }
      });
      req.addEventListener("error", function() {
        err("xhr failed");
      });
      req.open("POST", endpoint, true);
      req.send();
    }
    function default_err(err) {
      console.log("error", err);
    }
    var youtube_id = document.getElementById("youtube_id");
    var submit = document.getElementById("submit");
    var queue = document.getElementById("queue");
    var suggestions = document.getElementById("suggestions");
    var suggest = document.getElementById("suggest");
    var add = document.getElementById("add");
    var sub = document.getElementById("sub");
    var vol = document.getElementById("vol");
    function clear_suggestions() {
      suggestions.innerHTML = "";
    }
    var current_volume = null;
    function set_volume(vol) {
      current_volume = vol;
      json_request(function() {}, default_err, "setvolume?vol=" + vol);
      return current_volume;
    };
    add.onclick = function() {
      if (current_volume !== null) {
        set_volume(current_volume + 5);
      }
    };
    sub.onclick = function() {
      if (current_volume !== null) {
        set_volume(current_volume - 5);
      }
    };
    function reorder(uuid, direction) {
      json_request(function() {}, default_err, "/reorder?uuid=" + encodeURIComponent(uuid) + "&dir=" + encodeURIComponent("" + direction));
    }
    function render_suggestions(results) {
      var outline = "";
      for (var i = 0; i < results.length; i++) {
        outline += "<li><span></span><button>queue</button><button>up</button><button>down</button></li>";
      }
      suggestions.innerHTML = outline;
      for (var i = 0; i < results.length; i++) {
        suggestions.children[i].children[0].textContent = results[i].title;
        suggestions.children[i].children[1].onclick = function() {
          youtube_id.value = this;
          suggestions.innerHTML = "";
          submit.onclick();
        }.bind(results[i].ytid);
      }
    }
    suggest.onclick = function() {
      if (suggest.disabled) { return; }
      suggest.disabled = true;
      json_request(function(data) {
        render_suggestions(data);
        suggest.disabled = false;
      }, function(err) {
        console.log(err);
        suggest.disabled = false;
      }, "/search?q=" + encodeURIComponent(youtube_id.value));
    };
    youtube_id.onkeypress = function(e) {
      if (!e) { e = window.event; }
      clear_suggestions();
      var keyCode = e.keyCode || e.which;
      if (keyCode == 13) {
        submit.onclick();
        return false;
      }
    };
    submit.onclick = function() {
      if (youtube_id.disabled) { return; }
      youtube_id.disabled = true;
      json_request(function(data) {
        youtube_id.value = "";
        youtube_id.disabled = false;
      }, function(err) {
        console.log(err);
        youtube_id.disabled = false;
      }, "/enqueue?youtube_id=" + encodeURIComponent(youtube_id.value));
    };
    function delete_uuid(x) {
      json_request(function(data) {}, default_err, "/delete?uuid=" + encodeURIComponent(x));
    }
    function refresh() {
      json_request(function(data) {
        current_volume = data.volume;
        vol.textContent = current_volume !== null ? current_volume : "loading";
        var total = "";
        for (var i = 0; i < data.listing.length; i++) {
          total += "<li><span></span> | <button>delete</button> | <button>up</button> <button>down</button></li>";
        }
        queue.innerHTML = total;
        for (var i = 0; i < data.listing.length; i++) {
          var span = queue.children[i].children[0];
          var deleter = queue.children[i].children[1];
          var up = queue.children[i].children[2];
          var down = queue.children[i].children[3];
          var title = data.listing[i].ytid;
          if (data.titles[title]) {
            title = data.titles[title];
          } else {
            title += " (loading)";
          }
          span.innerText = title;
          deleter.onclick = (function() { delete_uuid(this); }).bind(data.listing[i].uuid);
          if (i == 0) {
            up.style.display = "none";
          }
          up.onclick = function() {
            reorder(this, -1);
          }.bind(data.listing[i].uuid);
          if (i == data.listing.length - 1) {
            down.style.display = "none";
          }
          down.onclick = function() {
            reorder(this, +1);
          }.bind(data.listing[i].uuid);
        }
      }, default_err, "/list");
    };
    setInterval(refresh, 1000);
  })();
</script>
</body>
</html>
"""

def query_search(query):
	try:
		return subprocess.check_output([os.path.join(os.getenv("HOME"), ".local/bin/youtube-dl"), "--get-id", "--", "%s" % query], cwd="/tmp").strip().decode()
	except:
		try:
			return subprocess.check_output([os.path.join(os.getenv("HOME"), ".local/bin/youtube-dl"), "--get-id", "--", "ytsearch:%s" % query], cwd="/tmp").strip().decode()
		except:
			return None

def query_search_multiple(query, n=5):
	try:
		lines = subprocess.check_output([os.path.join(os.getenv("HOME"), ".local/bin/youtube-dl"), "--get-id", "--get-title", "--", "ytsearch%d:%s" % (n, query)], cwd="/tmp").strip().decode().split("\n")
		assert len(lines) % 2 == 0
		return [{"title": ai, "ytid": bi} for ai, bi in zip(lines[::2], lines[1::2])]
	except:
		return None

def get_volume():
	try:
		elems = subprocess.check_output(["/usr/bin/amixer", "get", "Master"]).decode().split("[")
		elems = [e.split("]")[0] for e in elems]
		elems = [e for e in elems if e.endswith("%")]
		assert len(elems) == 1 and elems[0][-1] == "%"
		return int(elems[0][:-1], 10)
	except:
		return None

def set_volume(volume):
	try:
		volume = min(100, max(0, volume))
		subprocess.check_call(["/usr/bin/amixer", "set", "Master", "--", "%d%%" % volume])
	except:
		pass

class Musicazoo:
	def elems(self):
		return [json.loads(ent.decode()) for ent in redis.lrange("musicaqueue", 0, -1)]

	def titles(self, for_ytids):
		mapping = {}
		for ytid in for_ytids:
			value = redis.get("musicatitle.%s" % ytid)
			mapping[ytid] = value.decode() if value else None
		return mapping

	def find(self, uuid):
		found = [ent for ent in redis.lrange("musicaqueue", 0, -1) if json.loads(ent.decode())["uuid"] == uuid]
		assert len(found) <= 1
		return found[0] if found else None

	@cherrypy.expose
	def index(self):
		elems = self.elems()
		return index_html

	@cherrypy.expose
	@cherrypy.tools.json_out()
	def enqueue(self, youtube_id):
		youtube_id = query_search(youtube_id) if youtube_id else None
		if not youtube_id:
			return json.dumps({"success": False})
		redis.rpush("musicaqueue", json.dumps({"ytid": youtube_id, "uuid": str(uuid.uuid4())}))
		redis.rpush("musicaload", youtube_id)
		return {"success": True}

	@cherrypy.expose
	@cherrypy.tools.json_out()
	def list(self):
		elems = self.elems()
		return {"listing": elems, "titles": self.titles(set(elem["ytid"] for elem in elems)), "volume": get_volume()}

	@cherrypy.expose
	def delete(self, uuid):
		found = self.find(uuid)
		while found is not None:
			count = redis.lrem("musicaqueue", found)
			redis.rpush("musicaudit", "removed entry for %s at %s because of deletion request" % (found, time.ctime()))
			found = self.find(uuid)

	@cherrypy.expose
	def reorder(self, uuid, dir):
		try:
			forward = int(dir) >= 0
		except ValueError:
			return "faila"
		rel = 1 if forward else -1
		with redis.pipeline() as pipe:
			while True:
				try:
					pipe.watch("musicaqueue")
					cur_queue = pipe.lrange("musicaqueue", 0, -1)
					found = [ent for ent in cur_queue if json.loads(ent.decode())["uuid"] == uuid]
					if len(found) != 1:
						return "failb"
					cur_index = cur_queue.index(found[0])
					if (cur_index == 0 and not forward) or (cur_index == len(found) - 1 and forward):
						return "failc"
					pipe.multi()
					pipe.lset("musicaqueue", cur_index, cur_queue[cur_index + rel])
					pipe.lset("musicaqueue", cur_index + rel, cur_queue[cur_index])
					pipe.execute()
					break
				except WatchError:
					continue
		return "ok"

	@cherrypy.expose
	@cherrypy.tools.json_out()
	def search(self, q):
		return query_search_multiple(q)

	@cherrypy.expose
	@cherrypy.tools.json_out()
	def getvolume(self):
		return get_volume()

	@cherrypy.expose
	def setvolume(self, vol):
		try:
			set_volume(int(vol))
		except ValueError:
			pass

cherrypy.config.update({'server.socket_port': 8000})

cherrypy.tree.mount(Musicazoo(), "/")

cherrypy.engine.start()
cherrypy.engine.block()
